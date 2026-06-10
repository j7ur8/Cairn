from __future__ import annotations

from fastapi import APIRouter

from cairn.server.models_pkg.intents import (
    ReplayRunAdvanceResponse,
    ReplayRunCreateRequest,
    ReplayRunCreateResponse,
)
from cairn.server.replay_service import advance_replay_run as advance_replay_run_service
from cairn.server.replay_service import create_replay_run as create_replay_run_service

router = APIRouter(tags=["replay"])


@router.post(
    "/projects/{project_id}/replay-runs",
    response_model=ReplayRunCreateResponse,
    status_code=201,
)
def create_replay_run(project_id: str, body: ReplayRunCreateRequest):
    return create_replay_run_service(project_id, body)


@router.post(
    "/projects/{project_id}/replay-runs/advance",
    response_model=ReplayRunAdvanceResponse,
)
def advance_replay_run(project_id: str):
    return advance_replay_run_service(project_id)
