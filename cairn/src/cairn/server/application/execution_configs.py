from __future__ import annotations

from typing import Any

from cairn.server.domain.projects import require_project
from cairn.server.domain.time import utcnow
from cairn.server.execution_config import (
    load_project_execution_config,
    load_project_execution_configs,
    update_project_execution_config,
)
from cairn.server.models_pkg import UpdateExecutionConfigRequest
from cairn.server.repositories.projects import ProjectRepository


def get_project_execution_configs(conn: Any, project_id: str) -> dict[str, dict[str, Any]]:
    require_project(ProjectRepository(conn).get(project_id))
    return load_project_execution_configs(conn, project_id)


def get_project_execution_config(conn: Any, project_id: str, task_type: str) -> dict[str, Any]:
    require_project(ProjectRepository(conn).get(project_id))
    return load_project_execution_config(conn, project_id, task_type)


def patch_project_execution_config(
    conn: Any,
    project_id: str,
    body: UpdateExecutionConfigRequest,
) -> dict[str, dict[str, Any]]:
    projects = ProjectRepository(conn)
    require_project(projects.get(project_id))
    configs = update_project_execution_config(
        conn,
        project_id,
        capabilities=body.capabilities,
        ai_profiles=body.ai_profiles,
        role_id=body.role_id,
        proxy_id=body.proxy_id,
        role_id_set="role_id" in body.model_fields_set,
        proxy_id_set="proxy_id" in body.model_fields_set,
        task_timeouts=body.task_timeouts,
        now=utcnow(),
    )
    if "proxy_id" in body.model_fields_set:
        projects.update_proxy_id(project_id, body.proxy_id)
    return configs
