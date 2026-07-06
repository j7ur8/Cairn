from __future__ import annotations

from typing import Any

from cairn.server.capability_expansion import (
    CAIRN_RESOURCES_MCP_ID,
    project_capability_tasks,
    unavailable_capabilities,
)
from cairn.server.config.capabilities import list_yaml_capabilities
from cairn.server.domain.projects import require_project
from cairn.server.execution_config import execution_capabilities, load_project_execution_configs
from cairn.server.repositories.projects import ProjectRepository
from cairn.server.schemas import (
    CapabilityHealthEntry,
    CapabilityCatalogItem,
    ProjectCapabilityAuditCatalog,
    ProjectCapabilityAuditResponse,
    ProjectCapabilityAuditTask,
    ProjectCapabilitiesResponse,
    ProjectRole,
    ProjectRoleResponse,
)
from cairn.shared.task_types import builtin_task_type_names


def get_project_capabilities(conn: Any, project_id: str) -> ProjectCapabilitiesResponse:
    require_project(ProjectRepository(conn).get(project_id))
    configs = load_project_execution_configs(conn, project_id)
    catalog = _project_capability_catalog(configs)
    per_task = execution_capabilities(configs)
    health = {
        task: [
            CapabilityHealthEntry.model_validate(entry)
            for entry in ((configs.get(task) or {}).get("health", {}).get(task) or [])
        ]
        for task in builtin_task_type_names()
    }
    return ProjectCapabilitiesResponse(
        catalog=catalog,
        tasks=project_capability_tasks(per_task),
        health=health,
        unavailable=unavailable_capabilities(catalog, per_task),
    )


def get_project_capability_audit(conn: Any, project_id: str) -> ProjectCapabilityAuditResponse:
    require_project(ProjectRepository(conn).get(project_id))
    configs = load_project_execution_configs(conn, project_id)
    per_task = execution_capabilities(configs)
    catalog = list_yaml_capabilities()
    entry = next(
        (
            item
            for item in catalog
            if item.kind == "mcp_server" and item.id == CAIRN_RESOURCES_MCP_ID
        ),
        None,
    )
    task_types = list(entry.task_types) if entry is not None else []
    task_audit: dict[str, ProjectCapabilityAuditTask] = {}
    for task in builtin_task_type_names():
        capabilities = per_task.get(task)
        mcp_server_ids = list(capabilities.mcp_server_ids) if capabilities else []
        task_audit[task] = ProjectCapabilityAuditTask(
            task_type=task,
            has_cairn_resources=CAIRN_RESOURCES_MCP_ID in mcp_server_ids,
            mcp_server_ids=mcp_server_ids,
        )
    return ProjectCapabilityAuditResponse(
        project_id=project_id,
        mcp_server_id=CAIRN_RESOURCES_MCP_ID,
        catalog=ProjectCapabilityAuditCatalog(
            id=CAIRN_RESOURCES_MCP_ID,
            present=entry is not None,
            available=bool(entry and entry.available),
            task_types=task_types,
            supports_bootstrap="bootstrap" in task_types,
            supports_explore="explore" in task_types,
        ),
        tasks=task_audit,
    )


def _project_capability_catalog(configs: dict[str, dict[str, Any]]) -> list[CapabilityCatalogItem]:
    for task in builtin_task_type_names():
        raw_catalog = (configs.get(task) or {}).get("catalog")
        if not isinstance(raw_catalog, list):
            continue
        catalog: list[CapabilityCatalogItem] = []
        for raw_item in raw_catalog:
            if not isinstance(raw_item, dict):
                continue
            catalog.append(CapabilityCatalogItem.model_validate(raw_item))
        return catalog
    return list_yaml_capabilities()


def get_project_role(conn: Any, project_id: str) -> ProjectRoleResponse:
    require_project(ProjectRepository(conn).get(project_id))
    configs = load_project_execution_configs(conn, project_id)
    role = None
    for task in builtin_task_type_names():
        raw = (configs.get(task) or {}).get("role")
        if not isinstance(raw, dict):
            continue
        role = ProjectRole(
            project_id=project_id,
            role_id=str(raw.get("id") or ""),
            role_name=str(raw.get("name") or ""),
            role_prompt=str(raw.get("prompt") or ""),
            role_prompt_sha256=str(raw.get("prompt_sha256") or ""),
            created_at="",
        )
        break
    return ProjectRoleResponse(role=role)
