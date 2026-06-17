from __future__ import annotations

from typing import Any

from cairn.server.domain.projects import require_project
from cairn.server.execution_config import (
    load_project_execution_config,
    load_project_execution_configs,
)
from cairn.server.repositories.projects import ProjectRepository


def get_project_execution_configs(conn: Any, project_id: str) -> dict[str, dict[str, Any]]:
    require_project(ProjectRepository(conn).get(project_id))
    return load_project_execution_configs(conn, project_id)


def get_project_execution_config(conn: Any, project_id: str, task_type: str) -> dict[str, Any]:
    require_project(ProjectRepository(conn).get(project_id))
    return load_project_execution_config(conn, project_id, task_type)
