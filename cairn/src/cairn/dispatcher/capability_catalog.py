from __future__ import annotations

from typing import Any

from cairn.dispatcher.capability_mcp import runtime_mcp_args
from cairn.shared.config import DispatchConfig


def catalog_payload(config: DispatchConfig) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for mcp in config.capabilities.mcp_servers:
        payload.append(
            {
                "kind": "mcp_server",
                "id": mcp.id,
                "name": mcp.name,
                "description": mcp.description,
                "task_types": mcp.task_types,
                "available": True,
                "detail": mcp.transport,
                "source_path": mcp.source_path,
                "transport": mcp.transport,
                "command": mcp.command,
                "args": runtime_mcp_args(mcp, ""),
                "url": mcp.url,
                "headers": dict(mcp.headers),
                "probe_config": dict(mcp.probe_config),
                "required_skill_ids": list(mcp.required_skill_ids),
                "use_when": list(mcp.use_when),
                "activation_hint": mcp.activation_hint,
                "preferred_mcp_ids": [],
            }
        )
    for skill in config.capabilities.skills:
        payload.append(
            {
                "kind": "skill",
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "task_types": skill.task_types,
                "available": True,
                "detail": "directory",
                "source_path": skill.source_path,
                "use_when": list(skill.use_when),
                "activation_hint": skill.activation_hint,
                "preferred_mcp_ids": list(skill.preferred_mcp_ids),
            }
        )
    return payload
