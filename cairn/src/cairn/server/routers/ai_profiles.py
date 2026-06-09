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

from cairn.server.ai_profile_service import (
    load_project_ai_snapshots,
    persist_project_ai_selection,
    persist_project_ai_selections,
    require_complete_ai_profile_selections,
    task_ai_selections_from_snapshots,
)
from cairn.server.db import get_conn, with_immediate_tx
from cairn.server.models import (
    AiProfile,
    AiProfileCheckCompleteRequest,
    AiProfileCheckRequest,
    AiProfileCheckTriggerResponse,
    AiProfileCreate,
    AiProfileHealthReportRequest,
    AiProfileModelsReportRequest,
    AiProfileSyncRequest,
    AiProfileSyncWorker,
    AiProfileUpdate,
    AiProfileWithHealth,
    HealthCheckResult,
    ProjectAiProfilesResponse,
)
from cairn.server.yaml_config import (
    create_yaml_ai_profile,
    delete_yaml_ai_profile,
    get_yaml_ai_profile,
    list_yaml_ai_profiles,
    sync_yaml_ai_profiles,
    update_yaml_ai_profile_health,
    update_yaml_ai_profile_models,
    update_yaml_ai_profile,
    yaml_ai_profile_secret,
)
from cairn.server.security.secrets import decrypt_secret, encrypt_secret


router = APIRouter(tags=["ai-profiles"])


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_check_request_id() -> str:
    import uuid

    return f"aicheck_{uuid.uuid4().hex[:12]}"


@router.get("/ai-profiles", response_model=list[AiProfile])
def list_ai_profiles():
    return list_yaml_ai_profiles()


def _sync_profile_db_mirror(conn: Any, profile: AiProfile, *, sk: str | None = None) -> None:
    now = _utcnow()
    plaintext = _secret_for_storage(profile.sk if sk is None else sk)
    ciphertext = encrypt_secret(plaintext) if plaintext else ""
    conn.execute(
        """
        INSERT INTO ai_profiles (
            id, name, description, worker_type, provider, base_url, model,
            api_key_env, available, detail, healthcheck_timeout,
            seeded_from_worker, model_reasoning_effort, sk, sk_ciphertext,
            created_at, updated_at, last_health_ok, last_health_message, last_health_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            description = EXCLUDED.description,
            worker_type = EXCLUDED.worker_type,
            provider = EXCLUDED.provider,
            base_url = EXCLUDED.base_url,
            model = EXCLUDED.model,
            api_key_env = EXCLUDED.api_key_env,
            available = EXCLUDED.available,
            detail = EXCLUDED.detail,
            healthcheck_timeout = EXCLUDED.healthcheck_timeout,
            seeded_from_worker = EXCLUDED.seeded_from_worker,
            model_reasoning_effort = EXCLUDED.model_reasoning_effort,
            sk = EXCLUDED.sk,
            sk_ciphertext = EXCLUDED.sk_ciphertext,
            updated_at = EXCLUDED.updated_at,
            last_health_ok = EXCLUDED.last_health_ok,
            last_health_message = EXCLUDED.last_health_message,
            last_health_at = EXCLUDED.last_health_at
        """,
        (
            profile.id,
            profile.name,
            profile.description,
            profile.worker_type,
            profile.provider,
            profile.base_url,
            profile.model,
            profile.api_key_env,
            1 if profile.available else 0,
            profile.detail,
            profile.healthcheck_timeout,
            profile.seeded_from_worker,
            profile.model_reasoning_effort,
            ciphertext,
            profile.created_at or now,
            now,
            None if profile.last_health_ok is None else (1 if profile.last_health_ok else 0),
            profile.last_health_message,
            profile.last_health_at,
        ),
    )
    conn.execute("DELETE FROM ai_profile_models WHERE profile_id = ?", (profile.id,))
    for model in profile.models:
        conn.execute(
            "INSERT INTO ai_profile_models (profile_id, model, updated_at) VALUES (?, ?, ?)",
            (profile.id, model, now),
        )


def _sync_all_profile_db_mirrors(conn: Any, profiles: list[AiProfile]) -> None:
    ids = [profile.id for profile in profiles]
    for profile in profiles:
        _sync_profile_db_mirror(conn, profile)
    if ids:
        placeholders = ", ".join(f":id{i}" for i in range(len(ids)))
        params = {f"id{i}": value for i, value in enumerate(ids)}
        conn.execute(f"DELETE FROM ai_profile_models WHERE profile_id NOT IN ({placeholders})", params)
        conn.execute(f"DELETE FROM ai_profiles WHERE id NOT IN ({placeholders})", params)
    else:
        conn.execute("DELETE FROM ai_profile_models")
        conn.execute("DELETE FROM ai_profiles")


def _db_profile_secret(conn: Any, profile_id: str) -> str | None:
    row = conn.execute("SELECT sk_ciphertext, sk FROM ai_profiles WHERE id = ?", (profile_id,)).fetchone()
    if row is None:
        return None
    if row["sk_ciphertext"]:
        return decrypt_secret(row["sk_ciphertext"])
    return row["sk"] or None


def _secret_for_storage(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if text.startswith("${") and text.endswith("}"):
        return ""
    return text


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
    with get_conn() as conn:
        _sync_profile_db_mirror(conn, profile, sk=profile.sk)
        conn.commit()
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
    """Return the raw ``sk`` value for a profile. Dispatcher-only.

    The general-purpose ``GET /ai-profiles/{id}`` masks the value behind
    ``sk_set`` / ``sk_preview``; the dispatcher needs the actual token
    at task-launch time to inject it into the worker container env.
    Returns ``{"value": "<sk or null>"}``; ``null`` means the column is
    empty (operator relies on the host env). 404 for unknown ids.
    """
    try:
        value = yaml_ai_profile_secret(profile_id)
    except HTTPException:
        with get_conn() as conn:
            value = _db_profile_secret(conn, profile_id)
        if value is None:
            raise
    return {"value": value}


@router.put("/ai-profiles/{profile_id}", response_model=AiProfileWithHealth)
def update_ai_profile(profile_id: str, body: AiProfileUpdate):
    profile = update_yaml_ai_profile(profile_id, body)
    with get_conn() as conn:
        _sync_profile_db_mirror(conn, profile, sk=profile.sk)
        conn.commit()
    dump = profile.model_dump()
    dump["sk"] = profile.sk  # exclude=True stripped it; restore for re-wrap
    return AiProfileWithHealth(
        **dump,
        health=HealthCheckResult(ok=True, checks=[]),
    )


@router.delete("/ai-profiles/{profile_id}", status_code=204)
def delete_ai_profile(profile_id: str):
    delete_yaml_ai_profile(profile_id)
    with get_conn() as conn:
        conn.execute("DELETE FROM ai_profiles WHERE id = ?", (profile_id,))
        conn.commit()
    return None


@router.post("/ai-profiles/{profile_id}/check", response_model=AiProfileCheckTriggerResponse, status_code=202)
def trigger_ai_profile_check(profile_id: str, user=Depends(current_user_optional)):
    request_id = _new_check_request_id()
    now = _utcnow()
    requested_by = getattr(user, "email", None) or getattr(user, "id", None) or "unknown"
    with get_conn() as conn:
        profile = get_yaml_ai_profile(profile_id)
        _sync_profile_db_mirror(conn, profile, sk=profile.sk)
        existing = conn.execute(
            """
            SELECT *
            FROM ai_profile_check_requests
            WHERE profile_id = ?
              AND status IN ('pending', 'running')
            ORDER BY requested_at DESC
            LIMIT 1
            """,
            (profile_id,),
        ).fetchone()
        if existing is not None:
            current = _row_to_check_request(existing)
            return AiProfileCheckTriggerResponse(request_id=current.id, status=current.status)
        conn.execute(
            """
            INSERT INTO ai_profile_check_requests (
                id, profile_id, status, requested_at, requested_by
            ) VALUES (?, ?, 'pending', ?, ?)
            """,
            (request_id, profile_id, now, requested_by),
        )
        conn.commit()
    return AiProfileCheckTriggerResponse(request_id=request_id, status="pending")


@router.post("/ai-profiles/check-requests/claim", response_model=AiProfileCheckRequest | None)
def claim_ai_profile_check_request():
    now = _utcnow()
    with with_immediate_tx() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM ai_profile_check_requests
            WHERE status = 'pending'
            ORDER BY requested_at ASC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            """
            UPDATE ai_profile_check_requests
            SET status = 'running', started_at = ?, error_message = ''
            WHERE id = ?
            """,
            (now, row["id"]),
        )
        claimed = conn.execute(
            "SELECT * FROM ai_profile_check_requests WHERE id = ?",
            (row["id"],),
        ).fetchone()
        conn.commit()
    return _row_to_check_request(claimed)


@router.post("/ai-profiles/check-requests/{request_id}/complete", status_code=204)
def complete_ai_profile_check_request(request_id: str, body: AiProfileCheckCompleteRequest):
    now = _utcnow()
    status = "completed" if body.ok else "failed"
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM ai_profile_check_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"ai profile check request not found: {request_id}")
        conn.execute(
            """
            UPDATE ai_profile_check_requests
            SET status = ?, finished_at = ?, error_message = ?
            WHERE id = ?
            """,
            (status, now, (body.message or "")[:1000], request_id),
        )
        conn.commit()
    return None


# ---------------------------------------------------------------------------
# Sync + health report
# ---------------------------------------------------------------------------


@router.post("/ai-profiles/sync", response_model=list[AiProfileWithHealth])
def sync_ai_profiles(body: AiProfileSyncRequest):
    """Compatibility endpoint: dispatcher sync now writes dispatch.yaml."""
    profiles = sync_yaml_ai_profiles(body.workers)
    with get_conn() as conn:
        _sync_all_profile_db_mirrors(conn, profiles)
        conn.commit()
    return list_ai_profiles_with_health()


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
    with get_conn() as conn:
        for profile in list_yaml_ai_profiles():
            _sync_profile_db_mirror(conn, profile, sk=profile.sk)
        conn.commit()
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
    from cairn.server.models import HealthCheckItem
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
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
            raise HTTPException(404, f"project not found: {project_id}")
        catalog = list_yaml_ai_profiles()
        snapshots = load_project_ai_snapshots(conn, project_id)
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
