from __future__ import annotations

from typing import Any

from cairn.server.domain.errors import ServerInvariantError
from cairn.server.execution_config.assembler import load_project_execution_configs
from cairn.server.execution_config.models import TASK_TYPES
from cairn.server.models_pkg import (
    TaskCapabilities,
    TaskCapabilitiesMap,
    TaskCapabilitySelectionMap,
)
from cairn.server.models_pkg.ai_profiles import TaskAiProfileSelections
from cairn.shared.contracts import ProjectAiProfileSnapshot, TaskTimeouts


def update_project_execution_config(
    conn: Any,
    project_id: str,
    *,
    capabilities: TaskCapabilitySelectionMap | None = None,
    ai_profiles: TaskAiProfileSelections | None = None,
    role_id: str | None = None,
    proxy_id: str | None = None,
    role_id_set: bool = False,
    proxy_id_set: bool = False,
    task_timeouts: TaskTimeouts | None = None,
    now: str,
) -> dict[str, dict[str, Any]]:
    from cairn.server.execution_config import persist_project_execution_configs

    current = load_project_execution_configs(conn, project_id)
    next_timeouts = task_timeouts or execution_task_timeouts(current)
    next_ai_profiles = ai_profiles
    if next_ai_profiles is None:
        from cairn.server.models_pkg.ai_profiles import ai_selections_from_snapshots

        next_ai_profiles = ai_selections_from_snapshots(execution_ai_snapshots(current))
    next_capabilities = capabilities
    if next_capabilities is None:
        from cairn.server.models_pkg import CapabilitySelection

        expanded = execution_capabilities(current)
        next_capabilities = {
            task: CapabilitySelection(
                mcp_server_ids=list(selection.user_mcp_server_ids or []),
                skill_ids=list(selection.user_skill_ids or []),
            )
            for task, selection in expanded.items()
        }
    if role_id is None and not role_id_set:
        role = next((cfg.get("role") for cfg in current.values() if isinstance(cfg.get("role"), dict)), None)
        role_id = str(role.get("id")) if isinstance(role, dict) and role.get("id") else None
    if proxy_id is None and not proxy_id_set:
        proxy = next((cfg.get("proxy") for cfg in current.values() if isinstance(cfg.get("proxy"), dict)), None)
        proxy_id = str(proxy.get("id")) if isinstance(proxy, dict) and proxy.get("id") else None
    persist_project_execution_configs(
        conn,
        project_id,
        proxy_id=proxy_id,
        capabilities=next_capabilities,
        ai_profiles=next_ai_profiles,
        role_id=role_id,
        task_timeouts=next_timeouts,
        now=now,
    )
    return load_project_execution_configs(conn, project_id)


def execution_ai_snapshots(configs: dict[str, dict[str, Any]]) -> list[ProjectAiProfileSnapshot]:
    snapshots: list[ProjectAiProfileSnapshot] = []
    for task_type in TASK_TYPES:
        config = configs.get(task_type) or {}
        for item in config.get("ai_profiles") or []:
            if isinstance(item, dict):
                snapshots.append(ProjectAiProfileSnapshot.model_validate(item))
    return snapshots


def execution_capabilities(configs: dict[str, dict[str, Any]]) -> TaskCapabilitiesMap:
    out: TaskCapabilitiesMap = {}
    for task_type in TASK_TYPES:
        config = configs.get(task_type) or {}
        raw = config.get("capabilities") or {}
        out[task_type] = TaskCapabilities.model_validate(raw)
    return out


def execution_task_timeouts(configs: dict[str, dict[str, Any]]) -> TaskTimeouts:
    for task_type in TASK_TYPES:
        raw = (configs.get(task_type) or {}).get("task_timeouts")
        if isinstance(raw, dict):
            return TaskTimeouts.model_validate(raw)
    raise ServerInvariantError("project execution config missing task_timeouts")
