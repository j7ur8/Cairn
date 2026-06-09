from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cairn.dispatcher.config import DispatchConfig, WorkerConfig
from cairn.dispatcher.observability.reporter import ExecutionReporter
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.server.models import Intent, ProjectDetail


@dataclass(slots=True)
class WorkerTaskContext:
    config: DispatchConfig
    client: CairnClient
    container_manager: ContainerManager
    project: ProjectDetail
    worker: WorkerConfig
    task_type: str
    intent: Intent | None = None


def project_capability_data(
    client: CairnClient,
    project_id: str,
    reporter: ExecutionReporter,
    phase: str,
) -> dict | None:
    response = client.get_project_capabilities(project_id)
    if response.ok and isinstance(response.data, dict):
        return response.data
    reporter.emit_error(phase, "error", f"capability selection fetch failed status={response.status_code}")
    return None


def project_role_data(
    client: CairnClient,
    project_id: str,
    reporter: ExecutionReporter,
    phase: str,
) -> dict | None:
    response = client.get_project_role(project_id)
    if response.ok and isinstance(response.data, dict):
        return response.data
    reporter.emit_error(phase, "error", f"project role fetch failed status={response.status_code}")
    return None


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

    tasks = capability_data.get("tasks") if isinstance(capability_data.get("tasks"), dict) else {}
    task_state = tasks.get(task_type) if isinstance(tasks.get(task_type), dict) else {}
    snapshots = task_state.get("snapshots") if isinstance(task_state.get("snapshots"), list) else []
    catalog = capability_data.get("catalog") if isinstance(capability_data.get("catalog"), list) else []
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
    unavailable = capability_data.get("unavailable") if isinstance(capability_data.get("unavailable"), dict) else {}
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
