from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def capability_snapshots(capabilities: Mapping[str, Any]) -> list[dict[str, str]]:
    snapshots: list[dict[str, str]] = []
    user_mcp = set(_values(capabilities, "user_mcp_server_ids"))
    user_skill = set(_values(capabilities, "user_skill_ids"))
    role_default = set(_values(capabilities, "role_default_skill_ids"))
    for capability_id in _values(capabilities, "mcp_server_ids"):
        snapshots.append({
            "kind": "mcp_server",
            "capability_id": capability_id,
            "source": "selected" if capability_id in user_mcp else "required",
        })
    for capability_id in _values(capabilities, "skill_ids"):
        source = "selected" if capability_id in user_skill else "role_default" if capability_id in role_default else "required"
        snapshots.append({
            "kind": "skill",
            "capability_id": capability_id,
            "source": source,
        })
    return snapshots


def project_capability_tasks_payload(per_task: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    tasks: dict[str, dict[str, Any]] = {}
    for task, selection in per_task.items():
        capabilities = _selection_mapping(selection)
        tasks[str(task)] = {
            "selected": {
                "mcp_server_ids": _values(capabilities, "user_mcp_server_ids"),
                "skill_ids": _values(capabilities, "user_skill_ids"),
            },
            "snapshots": capability_snapshots(capabilities),
        }
    return tasks


def project_capability_data(execution_config: dict | None) -> dict | None:
    if not execution_config:
        return None
    task_type = str(execution_config.get("task_type") or "")
    capabilities_raw = execution_config.get("capabilities")
    capabilities = capabilities_raw if isinstance(capabilities_raw, dict) else {}
    catalog_raw = execution_config.get("catalog")
    catalog = catalog_raw if isinstance(catalog_raw, list) else []
    health_raw = execution_config.get("health")
    health = health_raw if isinstance(health_raw, dict) else {}
    return {
        "catalog": catalog,
        "tasks": {
            task_type: {
                "selected": {
                    "mcp_server_ids": _values(capabilities, "user_mcp_server_ids"),
                    "skill_ids": _values(capabilities, "user_skill_ids"),
                },
                "snapshots": capability_snapshots(capabilities),
            }
        },
        "health": health,
        "unavailable": {"mcp_server_ids": [], "skill_ids": []},
    }


def capability_manifest_payload(
    project_id: str,
    task_type: str,
    capability_data: dict[str, Any] | None,
) -> dict[str, Any]:
    if not capability_data:
        return {
            "summary": f"Project capabilities before {task_type}: no capability selection available",
            "project_id": project_id,
            "task_type": task_type,
            "mcp_servers": [],
            "skills": [],
            "unavailable": {"mcp_server_ids": [], "skill_ids": []},
        }

    tasks_raw = capability_data.get("tasks")
    tasks = tasks_raw if isinstance(tasks_raw, dict) else {}
    task_state_raw = tasks.get(task_type)
    task_state = task_state_raw if isinstance(task_state_raw, dict) else {}
    snapshots_raw = task_state.get("snapshots")
    snapshots = snapshots_raw if isinstance(snapshots_raw, list) else []
    catalog_raw = capability_data.get("catalog")
    catalog = catalog_raw if isinstance(catalog_raw, list) else []
    mcp_ids = [
        str(item.get("capability_id") or "").strip()
        for item in snapshots
        if isinstance(item, dict) and item.get("kind") == "mcp_server"
    ]
    skill_ids = [
        str(item.get("capability_id") or "").strip()
        for item in snapshots
        if isinstance(item, dict) and item.get("kind") == "skill"
    ]
    mcp_ids = [item for item in mcp_ids if item]
    skill_ids = [item for item in skill_ids if item]
    by_key = {
        (item.get("kind"), item.get("id")): item
        for item in catalog
        if isinstance(item, dict)
    }
    mcp_servers = [_manifest_item("mcp_server", capability_id, by_key, task_type) for capability_id in mcp_ids]
    skills = [_manifest_item("skill", capability_id, by_key, task_type) for capability_id in skill_ids]
    unavailable_raw = capability_data.get("unavailable")
    unavailable = unavailable_raw if isinstance(unavailable_raw, dict) else {}
    return {
        "summary": f"Project capabilities before {task_type}: {len(mcp_servers)} MCP servers, {len(skills)} skills",
        "project_id": project_id,
        "task_type": task_type,
        "mcp_servers": mcp_servers,
        "skills": skills,
        "unavailable": {
            "mcp_server_ids": _string_list(unavailable.get("mcp_server_ids")),
            "skill_ids": _string_list(unavailable.get("skill_ids")),
        },
    }


def _selection_mapping(selection: Any) -> dict[str, Any]:
    if isinstance(selection, Mapping):
        return dict(selection)
    return {
        "mcp_server_ids": getattr(selection, "mcp_server_ids", []),
        "skill_ids": getattr(selection, "skill_ids", []),
        "user_mcp_server_ids": getattr(selection, "user_mcp_server_ids", []),
        "user_skill_ids": getattr(selection, "user_skill_ids", []),
        "role_default_skill_ids": getattr(selection, "role_default_skill_ids", []),
    }


def _values(source: Mapping[str, Any], key: str) -> list[str]:
    value = source.get(key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _manifest_item(
    kind: str,
    capability_id: str,
    catalog: dict[tuple[Any, Any], dict[str, Any]],
    task_type: str,
) -> dict[str, Any]:
    item = catalog.get((kind, capability_id)) or {}
    task_types = _string_list(item.get("task_types"))
    return {
        "id": capability_id,
        "name": _string_value(item.get("name")) or capability_id,
        "detail": _string_value(item.get("detail")) or "",
        "task_types": task_types,
        "available": bool(item.get("available", False)),
        "enabled_for_task": task_type in task_types,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _string_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None

