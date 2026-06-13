from __future__ import annotations

from typing import Any

from cairn.dispatcher.capability_mcp import runtime_mcp_args
from cairn.shared.config import DispatchConfig


def catalog_payload(config: DispatchConfig) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for item in config.capabilities.mcp_servers:
        payload.append(
            {
                "kind": "mcp_server",
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "task_types": item.task_types,
                "available": True,
                "detail": item.transport,
                "source_path": item.source_path,
                "transport": item.transport,
                "command": item.command,
                "args": runtime_mcp_args(item, ""),
                "url": item.url,
                "headers": dict(item.headers),
                "probe_config": dict(item.probe_config),
                "required_skill_ids": list(item.required_skill_ids),
                "use_when": list(item.use_when),
                "activation_hint": item.activation_hint,
                "preferred_mcp_ids": [],
            }
        )
    for item in config.capabilities.skills:
        payload.append(
            {
                "kind": "skill",
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "task_types": item.task_types,
                "available": True,
                "detail": "directory",
                "source_path": item.source_path,
                "use_when": list(item.use_when),
                "activation_hint": item.activation_hint,
                "preferred_mcp_ids": list(item.preferred_mcp_ids),
            }
        )
    return payload
