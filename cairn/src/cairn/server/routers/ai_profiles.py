"""System-wide AI profile catalog and project-level primary/fallback selection.

AI profiles describe a concrete AI worker configuration (model, base URL, and
an env-var name that holds the API key). The settings UI manages the
shared catalog; new projects and replay runs pick exactly one *primary* and
an ordered list of *fallback* profiles. The dispatcher reads the project
snapshot and constrains worker selection to those profiles, applying
primary → fallback ordering before the existing worker priority.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from cairn.server import db
from cairn.server.application.ai_profiles import (
    claim_ai_profile_check_request as claim_ai_profile_check_request_command,
)
from cairn.server.application.ai_profiles import (
    complete_ai_profile_check_request as complete_ai_profile_check_request_command,
)
from cairn.server.application.ai_profiles import (
    project_ai_profiles,
    trigger_ai_profile_check_request,
)
from cairn.server.config.ai_profiles import (
    create_yaml_ai_profile,
    delete_yaml_ai_profile,
    get_yaml_ai_profile,
    list_yaml_ai_profiles,
    update_yaml_ai_profile,
    update_yaml_ai_profile_health,
    update_yaml_ai_profile_models,
    yaml_ai_profile_secret,
)
from cairn.server.models_pkg.ai_profiles import (
    AiProfileCheckCompleteRequest,
    AiProfileCheckRequest,
    AiProfileCheckTriggerResponse,
    AiProfileCreate,
    AiProfileHealthReportRequest,
    AiProfileModelsReportRequest,
    AiProfileUpdate,
    AiProfileWithHealth,
    ProjectAiProfilesResponse,
)
from cairn.server.security.deps import current_active_superuser
from cairn.shared.contracts import AiProfile, HealthCheckResult

router = APIRouter(tags=["ai-profiles"])


@router.get("/ai-profiles", response_model=list[AiProfile])
def list_ai_profiles():
    return list_yaml_ai_profiles()


@router.post("/ai-profiles", response_model=AiProfileWithHealth, status_code=201)
def create_ai_profile(body: AiProfileCreate, _superuser=Depends(current_active_superuser)):
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
def get_ai_profile_secret(profile_id: str, _superuser=Depends(current_active_superuser)) -> dict[str, str | None]:
    return {"value": yaml_ai_profile_secret(profile_id)}


@router.put("/ai-profiles/{profile_id}", response_model=AiProfileWithHealth)
def update_ai_profile(profile_id: str, body: AiProfileUpdate, _superuser=Depends(current_active_superuser)):
    profile = update_yaml_ai_profile(profile_id, body)
    dump = profile.model_dump()
    dump["sk"] = profile.sk  # exclude=True stripped it; restore for re-wrap
    return AiProfileWithHealth(
        **dump,
        health=HealthCheckResult(ok=True, checks=[]),
    )


@router.delete("/ai-profiles/{profile_id}", status_code=204)
def delete_ai_profile(profile_id: str, _superuser=Depends(current_active_superuser)):
    delete_yaml_ai_profile(profile_id)
    return None


@router.post("/ai-profiles/{profile_id}/check", response_model=AiProfileCheckTriggerResponse, status_code=202)
def trigger_ai_profile_check(profile_id: str, user=Depends(current_active_superuser)):
    requested_by = getattr(user, "email", None) or getattr(user, "id", None) or "unknown"
    with db.session_scope() as conn:
        get_yaml_ai_profile(profile_id)
        return trigger_ai_profile_check_request(
            conn,
            profile_id=profile_id,
            requested_by=requested_by,
        )


@router.post("/ai-profiles/check-requests/claim", response_model=AiProfileCheckRequest | None)
def claim_ai_profile_check_request(_superuser=Depends(current_active_superuser)):
    with db.session_scope() as conn:
        return claim_ai_profile_check_request_command(conn)


@router.post("/ai-profiles/check-requests/{request_id}/complete", status_code=204)
def complete_ai_profile_check_request(
    request_id: str,
    body: AiProfileCheckCompleteRequest,
    _superuser=Depends(current_active_superuser),
):
    with db.session_scope() as conn:
        complete_ai_profile_check_request_command(conn, request_id=request_id, body=body)
    return None


@router.post("/ai-profiles/health-report", status_code=204)
def post_health_report(body: AiProfileHealthReportRequest, _superuser=Depends(current_active_superuser)):
    """Dispatcher-side probe results, applied to the catalog and DB."""
    if not body.reports:
        return None
    from cairn.server.repositories.health_results import HealthCheckResultRepository

    with db.session_scope() as conn:
        repo = HealthCheckResultRepository(conn)
        for report in body.reports:
            update_yaml_ai_profile_health(report.profile_id, ok=report.ok, message=report.message or "")
            repo.insert(
                profile_id=report.profile_id,
                ok=report.ok,
                latency_ms=report.latency_ms,
                http_status=report.http_status,
                error_type=report.error_type,
                error_message=report.message or "",
                check_type=getattr(report, "check_type", "manual"),
            )
    return None


@router.post("/ai-profiles/models-report", status_code=204)
def post_models_report(body: AiProfileModelsReportRequest, _superuser=Depends(current_active_superuser)):
    """Dispatcher-side model list observations, cached for project creation."""
    if not body.reports:
        return None
    for report in body.reports:
        if report.models:
            update_yaml_ai_profile_models(report.profile_id, report.models)
    return None


def list_ai_profiles_with_health() -> list[AiProfileWithHealth]:
    """Return all profiles wrapped in ``AiProfileWithHealth`` (DB-backed)."""
    from cairn.server.repositories.health_results import HealthCheckResultRepository
    from cairn.shared.contracts import HealthCheckItem

    profiles = list_yaml_ai_profiles()
    result: list[AiProfileWithHealth] = []
    with db.session_scope() as conn:
        repo = HealthCheckResultRepository(conn)
        all_latest = {r["profile_id"]: r for r in repo.all_latest()}
    for profile in profiles:
        latest = all_latest.get(profile.id)
        if latest is not None:
            ok = bool(latest["ok"])
            checks = _build_health_checks(latest)
        else:
            ok = bool(profile.last_health_ok) if profile.last_health_ok is not None else True
            yaml_checks: list[HealthCheckItem] = []
            if profile.last_health_at is not None:
                yaml_checks.append(HealthCheckItem(
                    name="dispatcher_probe",
                    ok=ok,
                    message=profile.last_health_message or "ok",
                ))
            checks = yaml_checks
        dump = profile.model_dump()
        dump["sk"] = profile.sk
        result.append(AiProfileWithHealth(
            **dump,
            health=HealthCheckResult(ok=ok, checks=checks),
        ))
    return result


def _build_health_checks(row: dict) -> list:
    from cairn.shared.contracts import HealthCheckItem

    checks: list[HealthCheckItem] = []
    if row.get("latency_ms") is not None:
        checks.append(HealthCheckItem(
            name="latency",
            ok=True,
            message=f"{row['latency_ms']}ms",
        ))
    if row.get("error_type"):
        checks.append(HealthCheckItem(
            name="error",
            ok=False,
            message=f"{row['error_type']}: {row.get('error_message', '')}"[:500],
        ))
    if not checks:
        checks.append(HealthCheckItem(
            name="health",
            ok=bool(row["ok"]),
            message=row.get("error_message") or "ok",
        ))
    return checks


@router.get("/projects/{project_id}/ai-profiles", response_model=ProjectAiProfilesResponse)
def get_project_ai_profiles(project_id: str):
    with db.session_scope() as conn:
        return project_ai_profiles(conn, project_id)
