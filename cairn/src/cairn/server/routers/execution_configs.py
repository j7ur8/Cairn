from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cairn.server import db
from cairn.server.application.execution_configs import (
    get_project_execution_config as get_project_execution_config_query,
)
from cairn.server.application.execution_configs import (
    get_project_execution_configs as get_project_execution_configs_query,
)
from cairn.server.application.execution_configs import (
    patch_project_execution_config,
)
from cairn.server.models_pkg import UpdateExecutionConfigRequest

router = APIRouter(tags=["execution-configs"])


@router.get("/projects/{project_id}/execution-configs")
def get_execution_configs(project_id: str) -> dict[str, dict[str, Any]]:
    with db.session_scope() as conn:
        return get_project_execution_configs_query(conn, project_id)


@router.get("/projects/{project_id}/execution-configs/{task_type}")
def get_execution_config(project_id: str, task_type: str) -> dict[str, Any]:
    with db.session_scope() as conn:
        return get_project_execution_config_query(conn, project_id, task_type)


@router.patch("/projects/{project_id}/execution-config")
def patch_execution_config(project_id: str, body: UpdateExecutionConfigRequest) -> dict[str, dict[str, Any]]:
    with db.session_scope() as conn:
        return patch_project_execution_config(conn, project_id, body)
