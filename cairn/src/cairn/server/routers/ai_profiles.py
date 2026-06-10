"""System-wide AI profile catalog and project-level primary/fallback selection.

AI profiles describe a concrete AI worker configuration (model, base URL, and
an env-var name that holds the API key). The settings UI manages the
shared catalog; new projects and replay runs pick exactly one *primary* and
an ordered list of *fallback* profiles. The dispatcher reads the project
snapshot and constrains worker selection to those profiles, applying
primary → fallback ordering before the existing worker priority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from cairn.server.security.deps import current_user_optional
from fastapi import Depends

from cairn.server import db
from cairn.server.ai_profile_service import (
    task_ai_selections_from_snapshots,
)
from cairn.server.execution_config_service import (
    execution_ai_snapshots,
    load_worker_execution_configs,
)
from cairn.server.models_pkg.ai_profiles import (
    AiProfile,
    AiProfileCheckCompleteRequest,
    AiProfileCheckRequest,
    AiProfileCheckTriggerResponse,
    AiProfileCreate,
    AiProfileHealthReportRequest,
    AiProfileModelsReportRequest,
    AiProfileUpdate,
    AiProfileWithHealth,
    HealthCheckResult,
    ProjectAiProfilesResponse,
)
from cairn.server.repositories import sql
from cairn.server.config.ai_profiles import (
    create_yaml_ai_profile,
    delete_yaml_ai_profile,
    get_yaml_ai_profile,
    list_yaml_ai_profiles,
    update_yaml_ai_profile_health,
    update_yaml_ai_profile_models,
    update_yaml_ai_profile,
    yaml_ai_profile_secret,
)


router = APIRouter(tags=["ai-profiles"])


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_check_request_id() -> str:
    import uuid

    return f"aicheck_{uuid.uuid4().hex[:12]}"


@router.get("/ai-profiles", response_model=list[AiProfile])
def list_ai_profiles():
    return list_yaml_ai_profiles()


def _row_to_check_request(row: Any) -> AiProfileCheckRequest:
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


@router.post("/ai-profiles", response_model=AiProfileWithHealth, status_code=201)
def create_ai_profile(body: AiProfileCreate):
    profile = create_yaml_ai_profile(body)
    dump = profile.model_dump()
    dump["sk"] = profile.sk  # exclude=True stripped it; restore for re-wrap
    return AiProfileWithHealth(
        **dump,
        health=HealthCheckResult(ok=True, checks=[]),
    )


@router.get("/ai-profiles/{profile_id}", response_model=AiProfile)
def get_ai_profile(profile_id: str):
    return get_yaml_ai_profile(profile_id)


@router.get("/ai-profiles/{profile_id}/secret")
def get_ai_profile_secret(profile_id: str) -> dict[str, str | None]:
    return {"value": yaml_ai_profile_secret(profile_id)}


@router.put("/ai-profiles/{profile_id}", response_model=AiProfileWithHealth)
def update_ai_profile(profile_id: str, body: AiProfileUpdate):
    profile = update_yaml_ai_profile(profile_id, body)
    dump = profile.model_dump()
    dump["sk"] = profile.sk  # exclude=True stripped it; restore for re-wrap
    return AiProfileWithHealth(
        **dump,
        health=HealthCheckResult(ok=True, checks=[]),
    )


@router.delete("/ai-profiles/{profile_id}", status_code=204)
def delete_ai_profile(profile_id: str):
    delete_yaml_ai_profile(profile_id)
    return None


@router.post("/ai-profiles/{profile_id}/check", response_model=AiProfileCheckTriggerResponse, status_code=202)
def trigger_ai_profile_check(profile_id: str, user=Depends(current_user_optional)):
    request_id = _new_check_request_id()
    now = _utcnow()
    requested_by = getattr(user, "email", None) or getattr(user, "id", None) or "unknown"
    with db.session_scope() as conn:
        get_yaml_ai_profile(profile_id)
        existing = sql.fetchone(
            conn,
            """
            SELECT *
            FROM ai_profile_check_requests
            WHERE profile_id = :profile_id
              AND status IN ('pending', 'running')
            ORDER BY requested_at DESC
            LIMIT 1
            """,
            {"profile_id": profile_id},
        )
        if existing is not None:
            current = _row_to_check_request(existing)
            return AiProfileCheckTriggerResponse(request_id=current.id, status=current.status)
        sql.execute(
            conn,
            """
            INSERT INTO ai_profile_check_requests (
                id, profile_id, status, requested_at, requested_by
            ) VALUES (:id, :profile_id, 'pending', :requested_at, :requested_by)
            """,
            {
                "id": request_id,
                "profile_id": profile_id,
                "requested_at": now,
                "requested_by": requested_by,
            },
        )
    return AiProfileCheckTriggerResponse(request_id=request_id, status="pending")


@router.post("/ai-profiles/check-requests/claim", response_model=AiProfileCheckRequest | None)
def claim_ai_profile_check_request():
    now = _utcnow()
    with db.session_scope() as conn:
        row = sql.fetchone(
            conn,
            """
            SELECT *
            FROM ai_profile_check_requests
            WHERE status = 'pending'
            ORDER BY requested_at ASC
            LIMIT 1
            """
        )
        if row is None:
            return None
        sql.execute(
            conn,
            """
            UPDATE ai_profile_check_requests
            SET status = 'running', started_at = :started_at, error_message = ''
            WHERE id = :id
            """,
            {"started_at": now, "id": row["id"]},
        )
        claimed = sql.fetchone(
            conn,
            "SELECT * FROM ai_profile_check_requests WHERE id = :id",
            {"id": row["id"]},
        )
    return _row_to_check_request(claimed)


@router.post("/ai-profiles/check-requests/{request_id}/complete", status_code=204)
def complete_ai_profile_check_request(request_id: str, body: AiProfileCheckCompleteRequest):
    now = _utcnow()
    status = "completed" if body.ok else "failed"
    with db.session_scope() as conn:
        row = sql.fetchone(
            conn,
            "SELECT id FROM ai_profile_check_requests WHERE id = :id",
            {"id": request_id},
        )
        if row is None:
            raise HTTPException(404, f"ai profile check request not found: {request_id}")
        sql.execute(
            conn,
            """
            UPDATE ai_profile_check_requests
            SET status = :status, finished_at = :finished_at, error_message = :error_message
            WHERE id = :id
            """,
            {
                "status": status,
                "finished_at": now,
                "error_message": (body.message or "")[:1000],
                "id": request_id,
            },
        )
    return None


@router.post("/ai-profiles/health-report", status_code=204)
def post_health_report(body: AiProfileHealthReportRequest):
    """Dispatcher-side probe results, applied to the catalog.

    The dispatcher runs the real probe (env var resolution + TCP connect)
    because the server cannot see the operator's secrets. After this
    endpoint is called, ``available`` reflects the latest probe outcome.
    """
    if not body.reports:
        return None
    now = _utcnow()
    for report in body.reports:
        update_yaml_ai_profile_health(report.profile_id, ok=report.ok, message=report.message or "")
    return None


@router.post("/ai-profiles/models-report", status_code=204)
def post_models_report(body: AiProfileModelsReportRequest):
    """Dispatcher-side model list observations, cached for project creation."""
    if not body.reports:
        return None
    for report in body.reports:
        if report.models:
            update_yaml_ai_profile_models(report.profile_id, report.models)
    return None


def list_ai_profiles_with_health() -> list[AiProfileWithHealth]:
    """Return all profiles wrapped in ``AiProfileWithHealth``.

    The server does not run the probe itself; the dispatcher is the
    authoritative source of truth for the probe (because it has the env
    vars and the network). This helper just rolls the last known
    ``last_health_*`` columns into a ``HealthCheckResult`` payload so the
    UI can render a single "health" badge per row.
    """
    from cairn.server.models_pkg.ai_profiles import HealthCheckItem
    profiles = list_yaml_ai_profiles()
    result: list[AiProfileWithHealth] = []
    for profile in profiles:
        ok = bool(profile.last_health_ok) if profile.last_health_ok is not None else True
        checks: list[HealthCheckItem] = []
        if profile.last_health_at is not None:
            checks.append(HealthCheckItem(
                name="dispatcher_probe",
                ok=ok,
                message=profile.last_health_message or "ok",
            ))
        dump = profile.model_dump()
        dump["sk"] = profile.sk  # exclude=True stripped it; restore
        result.append(AiProfileWithHealth(
            **dump,
            health=HealthCheckResult(ok=ok, checks=checks),
        ))
    return result


@router.get("/projects/{project_id}/ai-profiles", response_model=ProjectAiProfilesResponse)
def get_project_ai_profiles(project_id: str):
    with db.session_scope() as conn:
        if sql.fetchone(conn, "SELECT 1 FROM projects WHERE id = :project_id", {"project_id": project_id}) is None:
            raise HTTPException(404, f"project not found: {project_id}")
        configs = load_worker_execution_configs(conn, project_id)
        catalog = list_yaml_ai_profiles()
        snapshots = execution_ai_snapshots(configs)
        selections = task_ai_selections_from_snapshots(snapshots)
        available_ids = {item.id for item in catalog if item.available}
        unavailable = sorted({
            snap.profile_id for snap in snapshots
            if snap.profile_id not in available_ids
        })
        return ProjectAiProfilesResponse(
            catalog=catalog,
            selections=selections,
            snapshots=snapshots,
            unavailable_profile_ids=unavailable,
        )
