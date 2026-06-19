from __future__ import annotations

import uuid
from typing import Any

from cairn.server.ai_profile_service import task_ai_selections_from_snapshots
from cairn.server.config.ai_profiles import list_yaml_ai_profiles, update_yaml_ai_profile_health
from cairn.server.domain.errors import NotFoundError
from cairn.server.domain.time import utcnow
from cairn.server.execution_config import execution_ai_snapshots, load_project_execution_configs
from cairn.server.repositories.ai_profiles import AiProfileCheckRepository
from cairn.server.repositories.health_results import HealthCheckResultRepository
from cairn.server.repositories.projects import ProjectRepository
from cairn.server.schemas.ai_profiles import (
    AiProfileCheckCompleteRequest,
    AiProfileCheckRequest,
    AiProfileCheckTriggerResponse,
    AiProfileHealthReportRequest,
    AiProfileWithHealth,
    ProjectAiProfilesResponse,
)
from cairn.shared.contracts import HealthCheckItem, HealthCheckResult


def new_check_request_id() -> str:
    return f"aicheck_{uuid.uuid4().hex[:12]}"


def row_to_check_request(row: Any) -> AiProfileCheckRequest:
    return AiProfileCheckRequest(
        id=row["id"],
        profile_id=row["profile_id"],
        status=row["status"],
        requested_at=row["requested_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        requested_by=row["requested_by"] or "",
        error_message=row["error_message"] or "",
    )


def trigger_ai_profile_check_request(
    conn: Any,
    *,
    profile_id: str,
    requested_by: str,
) -> AiProfileCheckTriggerResponse:
    repo = AiProfileCheckRepository(conn)
    existing = repo.latest_active_for_profile(profile_id)
    if existing is not None:
        current = row_to_check_request(existing)
        # latest_active_for_profile filters status IN ('pending','running'),
        # so the broad CheckRequest literal is always one of those here.
        assert current.status in ("pending", "running")
        return AiProfileCheckTriggerResponse(request_id=current.id, status=current.status)

    request_id = new_check_request_id()
    repo.insert_pending(
        request_id=request_id,
        profile_id=profile_id,
        requested_at=utcnow(),
        requested_by=requested_by,
    )
    return AiProfileCheckTriggerResponse(request_id=request_id, status="pending")


def claim_ai_profile_check_request(conn: Any) -> AiProfileCheckRequest | None:
    row = AiProfileCheckRepository(conn).claim_next(started_at=utcnow())
    return row_to_check_request(row) if row is not None else None


def complete_ai_profile_check_request(
    conn: Any,
    *,
    request_id: str,
    body: AiProfileCheckCompleteRequest,
) -> None:
    repo = AiProfileCheckRepository(conn)
    if repo.get(request_id) is None:
        raise NotFoundError(f"ai profile check request not found: {request_id}")
    repo.complete(
        request_id=request_id,
        status="completed" if body.ok else "failed",
        finished_at=utcnow(),
        error_message=(body.message or "")[:1000],
    )


def apply_ai_profile_health_report(conn: Any, body: AiProfileHealthReportRequest) -> None:
    repo = HealthCheckResultRepository(conn)
    for report in body.reports:
        update_yaml_ai_profile_health(
            report.profile_id,
            ok=report.ok,
            message=report.message or "",
        )
        repo.insert(
            profile_id=report.profile_id,
            ok=report.ok,
            latency_ms=report.latency_ms,
            http_status=report.http_status,
            error_type=report.error_type,
            error_message=report.message or "",
            check_type=getattr(report, "check_type", "manual"),
        )


def list_ai_profiles_with_health(conn: Any) -> list[AiProfileWithHealth]:
    """Return all profiles wrapped in ``AiProfileWithHealth`` (DB-backed)."""
    profiles = list_yaml_ai_profiles()
    result: list[AiProfileWithHealth] = []
    repo = HealthCheckResultRepository(conn)
    all_latest = {row["profile_id"]: row for row in repo.all_latest()}
    for profile in profiles:
        latest = all_latest.get(profile.id)
        checks: list[HealthCheckItem]
        if latest is not None:
            ok = bool(latest["ok"])
            checks = _build_health_checks(latest)
        else:
            ok = bool(profile.last_health_ok) if profile.last_health_ok is not None else True
            checks = []
            if profile.last_health_at is not None:
                checks.append(
                    HealthCheckItem(
                        name="dispatcher_probe",
                        ok=ok,
                        message=profile.last_health_message or "ok",
                    )
                )
        dump = profile.model_dump()
        dump["sk"] = profile.sk
        result.append(
            AiProfileWithHealth(
                **dump,
                health=HealthCheckResult(ok=ok, checks=checks),
            )
        )
    return result


def _build_health_checks(row: dict[str, Any]) -> list[HealthCheckItem]:
    checks: list[HealthCheckItem] = []
    if row.get("latency_ms") is not None:
        checks.append(
            HealthCheckItem(
                name="latency",
                ok=True,
                message=f"{row['latency_ms']}ms",
            )
        )
    if row.get("error_type"):
        checks.append(
            HealthCheckItem(
                name="error",
                ok=False,
                message=f"{row['error_type']}: {row.get('error_message', '')}"[:500],
            )
        )
    if not checks:
        checks.append(
            HealthCheckItem(
                name="health",
                ok=bool(row["ok"]),
                message=row.get("error_message") or "ok",
            )
        )
    return checks


def project_ai_profiles(conn: Any, project_id: str) -> ProjectAiProfilesResponse:
    if ProjectRepository(conn).get(project_id) is None:
        raise NotFoundError(f"project not found: {project_id}")
    configs = load_project_execution_configs(conn, project_id)
    catalog = list_yaml_ai_profiles()
    snapshots = execution_ai_snapshots(configs)
    selections = task_ai_selections_from_snapshots(snapshots)
    available_ids = {item.id for item in catalog if item.available}
    unavailable = sorted(
        {
            snapshot.profile_id
            for snapshot in snapshots
            if snapshot.profile_id not in available_ids
        }
    )
    return ProjectAiProfilesResponse(
        catalog=catalog,
        selections=selections,
        snapshots=snapshots,
        unavailable_profile_ids=unavailable,
    )
