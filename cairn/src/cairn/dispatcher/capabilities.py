from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cairn.dispatcher.config import DispatchConfig, McpServerCapabilityConfig, SkillCapabilityConfig, TaskType
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.workers.base import WorkerExecutionContext

CAPABILITY_ROOT = "/tmp/cairn-capabilities"


@dataclass(slots=True)
class CapabilityInjection:
    instructions: str
    summary: str
    mcp_servers: list[str]
    skills: list[str]
    errors: list[str]
    context: WorkerExecutionContext


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
                "detail": "stdio",
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
            }
        )
    return payload


def inject_project_capabilities(
    config: DispatchConfig,
    container_manager: ContainerManager,
    container_name: str,
    project_id: str,
    task_type: TaskType,
    task_instance_id: str,
    selection_data: dict[str, Any] | None,
) -> CapabilityInjection:
    if not selection_data:
        return CapabilityInjection("", "no capability selection available", [], [], [], WorkerExecutionContext())

    selection = selection_data.get("selection") if isinstance(selection_data.get("selection"), dict) else {}
    selected_mcp = _string_list(selection.get("mcp_server_ids"))
    selected_skills = _string_list(selection.get("skill_ids"))
    mcp_by_id = {item.id: item for item in config.capabilities.mcp_servers}
    skill_by_id = {item.id: item for item in config.capabilities.skills}
    errors: list[str] = []

    mcp_servers: list[McpServerCapabilityConfig] = []
    for capability_id in selected_mcp:
        item = mcp_by_id.get(capability_id)
        if item is None:
            errors.append(f"mcp_server:{capability_id}: not declared in dispatch config")
            continue
        if task_type not in item.task_types:
            errors.append(f"mcp_server:{capability_id}: not enabled for task type {task_type}")
            continue
        mcp_servers.append(item)

    skills: list[SkillCapabilityConfig] = []
    for capability_id in selected_skills:
        item = skill_by_id.get(capability_id)
        if item is None:
            errors.append(f"skill:{capability_id}: not declared in dispatch config")
            continue
        if task_type not in item.task_types:
            errors.append(f"skill:{capability_id}: not enabled for task type {task_type}")
            continue
        skills.append(item)

    if not mcp_servers and not skills:
        return CapabilityInjection("", _summary([], [], errors), [], [], errors, WorkerExecutionContext())

    capability_root = f"{CAPABILITY_ROOT}/{_safe_path_segment(project_id)}/{_safe_path_segment(task_instance_id)}"
    mcp_root = f"{capability_root}/mcp"
    mcp_path = f"{capability_root}/mcp.json"
    skill_root = f"{capability_root}/skills"
    injected_mcp_servers = list(mcp_servers)
    injected_skills: list[SkillCapabilityConfig] = []
    injected_mcp_details: list[dict[str, Any]] = []
    if mcp_servers:
        for mcp in mcp_servers:
            if not mcp.source_path:
                continue
            try:
                container_manager.write_directory(container_name, f"{mcp_root}/{mcp.id}", Path(mcp.source_path))
            except Exception as exc:
                errors.append(f"mcp_server:{mcp.id}: failed to inject directory: {exc}")
                injected_mcp_servers = [item for item in injected_mcp_servers if item.id != mcp.id]
        try:
            container_manager.write_text_file(container_name, mcp_path, _mcp_json(injected_mcp_servers, capability_root))
        except Exception as exc:
            errors.append(f"mcp_servers: failed to write config: {exc}")
            injected_mcp_servers = []
        injected_mcp_details = [_mcp_detail(item, capability_root) for item in injected_mcp_servers]
    for skill in skills:
        try:
            container_manager.write_directory(container_name, f"{skill_root}/{skill.id}", Path(skill.source_path))
        except Exception as exc:
            errors.append(f"skill:{skill.id}: failed to inject directory: {exc}")
            continue
        injected_skills.append(skill)

    instructions = _instructions(mcp_path, skill_root, injected_mcp_servers, injected_skills)
    return CapabilityInjection(
        instructions=instructions,
        summary=_summary([item.id for item in injected_mcp_servers], [item.id for item in injected_skills], errors),
        mcp_servers=[item.id for item in injected_mcp_servers],
        skills=[item.id for item in injected_skills],
        errors=errors,
        context=WorkerExecutionContext(
            capability_root=capability_root if (injected_mcp_servers or injected_skills) else "",
            mcp_config_path=mcp_path if injected_mcp_servers else "",
            skill_root=skill_root if injected_skills else "",
            mcp_servers=injected_mcp_details,
            skills=[item.id for item in injected_skills],
        ),
    )


def _mcp_json(mcp_servers: list[McpServerCapabilityConfig], capability_root: str) -> str:
    payload = {
        "mcpServers": {
            item.id: _mcp_config_detail(item, capability_root)
            for item in mcp_servers
        }
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _mcp_config_detail(item: McpServerCapabilityConfig, capability_root: str) -> dict[str, Any]:
    return {
        "command": _render_capability_path(item.command, capability_root),
        "args": [_render_capability_path(arg, capability_root) for arg in item.args],
        "env": {key: _render_capability_path(value, capability_root) for key, value in item.env.items()},
    }


def _mcp_detail(item: McpServerCapabilityConfig, capability_root: str) -> dict[str, Any]:
    detail = {
        "id": item.id,
        **_mcp_config_detail(item, capability_root),
    }
    return detail


def _render_capability_path(value: str, capability_root: str) -> str:
    return value.replace("{capability_root}", capability_root)


def _instructions(
    mcp_path: str,
    skill_root: str,
    mcp_servers: list[McpServerCapabilityConfig],
    skills: list[SkillCapabilityConfig],
) -> str:
    lines = ["# Project Capabilities", "Authorized project capabilities are available inside this container.", ""]
    if mcp_servers:
        lines.extend(
            [
                f"- MCP server config file: {mcp_path}",
                "- MCP servers:",
                *[f"  - {item.id}: {item.name}" for item in mcp_servers],
                "",
            ]
        )
    if skills:
        lines.extend(
            [
                f"- Skill directory root: {skill_root}",
                "- Skills:",
                *[f"  - {item.id}: {item.name} at {skill_root}/{item.id}" for item in skills],
                "",
            ]
        )
    lines.extend(
        [
            "Use these capabilities only for the current Cairn project/challenge.",
            "Do not treat capability availability as a solved fact.",
            "Only report findings that are verified against the challenge target.",
        ]
    )
    return "\n".join(lines)


def _summary(mcp_ids: list[str], skill_ids: list[str], errors: list[str]) -> str:
    return json.dumps(
        {"mcp_servers": mcp_ids, "skills": skill_ids, "errors": errors},
        ensure_ascii=False,
        indent=2,
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _safe_path_segment(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    text = text.strip("._")
    return text or "unknown"
