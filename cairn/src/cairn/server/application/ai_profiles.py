from __future__ import annotations

import uuid
from typing import Any

from cairn.server.ai_profile_service import task_ai_selections_from_snapshots
from cairn.server.config.ai_profiles import list_yaml_ai_profiles
from cairn.server.domain.errors import NotFoundError
from cairn.server.domain.time import utcnow
from cairn.server.execution_config import execution_ai_snapshots, load_project_execution_configs
from cairn.server.models_pkg.ai_profiles import (
    AiProfileCheckCompleteRequest,
    AiProfileCheckRequest,
    AiProfileCheckTriggerResponse,
    ProjectAiProfilesResponse,
)
from cairn.server.repositories.ai_profiles import AiProfileCheckRepository
from cairn.server.repositories.projects import ProjectRepository


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
