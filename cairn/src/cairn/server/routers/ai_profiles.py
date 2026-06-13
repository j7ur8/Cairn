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
    """Dispatcher-side probe results, applied to the catalog.

    The dispatcher runs the real probe (env var resolution + TCP connect)
    because the server cannot see the operator's secrets. After this
    endpoint is called, ``available`` reflects the latest probe outcome.
    """
    if not body.reports:
        return None
    for report in body.reports:
        update_yaml_ai_profile_health(report.profile_id, ok=report.ok, message=report.message or "")
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
    """Return all profiles wrapped in ``AiProfileWithHealth``.

    The server does not run the probe itself; the dispatcher is the
    authoritative source of truth for the probe (because it has the env
    vars and the network). This helper just rolls the last known
    ``last_health_*`` columns into a ``HealthCheckResult`` payload so the
    UI can render a single "health" badge per row.
    """
    from cairn.shared.contracts import HealthCheckItem
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
        return project_ai_profiles(conn, project_id)
