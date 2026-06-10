from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cairn.server import db
from cairn.server.execution_config_service import (
    load_worker_execution_config,
    load_worker_execution_configs,
)
from cairn.server.services import get_project_or_404


router = APIRouter(tags=["execution-configs"])


@router.get("/projects/{project_id}/execution-configs")
def get_execution_configs(project_id: str) -> dict[str, dict[str, Any]]:
    with db.session_scope() as conn:
        get_project_or_404(conn, project_id)
        return load_worker_execution_configs(conn, project_id)


@router.get("/projects/{project_id}/execution-configs/{task_type}")
def get_execution_config(project_id: str, task_type: str) -> dict[str, Any]:
    with db.session_scope() as conn:
        get_project_or_404(conn, project_id)
        return load_worker_execution_config(conn, project_id, task_type)
