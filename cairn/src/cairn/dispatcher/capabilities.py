from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from cairn.dispatcher.capability_catalog import catalog_payload  # noqa: F401  (re-exported for consumers/tests)
from cairn.dispatcher.capability_constants import CAPABILITY_ROOT
from cairn.dispatcher.capability_instructions import (
    instructions,
    summary,
)
from cairn.dispatcher.capability_mcp import (
    claude_plugin_json,
    mcp_detail,
    mcp_json,
)
from cairn.dispatcher.capability_probe import validate_selected_mcp
from cairn.dispatcher.prompt_resources import load_prompt_group_files_appendix
from cairn.dispatcher.workers.base import WorkerExecutionContext
from cairn.shared.config import DispatchConfig, McpServerCapabilityConfig, SkillCapabilityConfig, TaskType

LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class CapabilityInjection:
    instructions: str
    summary: str
    mcp_servers: list[str]
    skills: list[str]
    errors: list[str]
    context: WorkerExecutionContext


class CapabilityWriter(Protocol):
    def write_text_file(self, container_name: str, path: str, content: str) -> None: ...

    def write_directory(self, container_name: str, path: str, source: Path) -> None: ...


def inject_project_capabilities(
    config: DispatchConfig,
    prompt_group: str,
    container_manager: CapabilityWriter,
    container_name: str,
    project_id: str,
    task_type: TaskType,
    task_instance_id: str,
    selection_data: dict[str, Any] | None,
) -> CapabilityInjection:
    if task_type == "reason":
        return CapabilityInjection("", "", [], [], [], WorkerExecutionContext())

    include_files_appendix = task_type != "reason"
    files_errors: list[str] = []
    files_appendix = ""
    if include_files_appendix:
        files_appendix, files_errors = load_prompt_group_files_appendix(prompt_group)

    def render_files_only_instructions() -> str:
        if not files_appendix.strip():
            return ""
        return instructions("", "", [], [], files_appendix=files_appendix)

    if not selection_data:
        if not include_files_appendix:
            return CapabilityInjection("", "no capability selection available", [], [], [], WorkerExecutionContext())
        return CapabilityInjection(
            render_files_only_instructions(),
            "no capability selection available",
            [],
            [],
            files_errors,
            WorkerExecutionContext(),
        )

    tasks_raw = selection_data.get("tasks")
    tasks = tasks_raw if isinstance(tasks_raw, dict) else {}
    task_state_raw = tasks.get(task_type)
    task_state = task_state_raw if isinstance(task_state_raw, dict) else {}
    snapshots_raw = task_state.get("snapshots")
    snapshots = snapshots_raw if isinstance(snapshots_raw, list) else []
    selected_mcp = [
        str(item.get("capability_id") or "").strip()
        for item in snapshots
        if isinstance(item, dict) and item.get("kind") == "mcp_server"
    ]
    selected_skills = [
        str(item.get("capability_id") or "").strip()
        for item in snapshots
        if isinstance(item, dict) and item.get("kind") == "skill"
    ]
    selected_mcp = [item for item in selected_mcp if item]
    selected_skills = [item for item in selected_skills if item]
    mcp_by_id = {item.id: item for item in config.capabilities.mcp_servers}
    skill_by_id = {item.id: item for item in config.capabilities.skills}
    errors: list[str] = list(files_errors)

    mcp_servers: list[McpServerCapabilityConfig] = []
    for capability_id in selected_mcp:
        item = mcp_by_id.get(capability_id)
        if item is None:
            errors.append(f"mcp_server:{capability_id}: not declared in dispatch config")
            continue
        if task_type not in item.task_types:
            LOG.info(
                "skip mcp_server=%s because task_type=%s is not enabled enabled_task_types=%s",
                capability_id,
                task_type,
                item.task_types,
            )
            continue
        probe_error = validate_selected_mcp(item, task_type)
        if probe_error:
            errors.append(probe_error)
            continue
        mcp_servers.append(item)

    skills: list[SkillCapabilityConfig] = []
    for capability_id in selected_skills:
        skill = skill_by_id.get(capability_id)
        if skill is None:
            errors.append(f"skill:{capability_id}: not declared in dispatch config")
            continue
        if task_type not in skill.task_types:
            LOG.info(
                "skip skill=%s because task_type=%s is not enabled enabled_task_types=%s",
                capability_id,
                task_type,
                skill.task_types,
            )
            continue
        skills.append(skill)

    if not mcp_servers and not skills:
        if not include_files_appendix:
            return CapabilityInjection("", summary([], [], errors), [], [], errors, WorkerExecutionContext())
        return CapabilityInjection(
            render_files_only_instructions(),
            summary([], [], errors),
            [],
            [],
            errors,
            WorkerExecutionContext(),
        )

    capability_root = f"{CAPABILITY_ROOT}/{_safe_path_segment(project_id)}/{_safe_path_segment(task_instance_id)}"
    mcp_root = f"{capability_root}/mcp"
    mcp_path = f"{capability_root}/mcp.json"
    skill_root = f"{capability_root}/skills"
    claude_plugin_dir = f"{capability_root}/claude-plugin"
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
            container_manager.write_text_file(container_name, mcp_path, mcp_json(injected_mcp_servers, capability_root))
        except Exception as exc:
            errors.append(f"mcp_servers: failed to write config: {exc}")
            injected_mcp_servers = []
        injected_mcp_details = [mcp_detail(item, capability_root) for item in injected_mcp_servers]
    for skill in skills:
        try:
            container_manager.write_directory(container_name, f"{skill_root}/{skill.id}", Path(skill.source_path))
        except Exception as exc:
            errors.append(f"skill:{skill.id}: failed to inject directory: {exc}")
            continue
        injected_skills.append(skill)
    if injected_skills:
        try:
            container_manager.write_text_file(
                container_name,
                f"{claude_plugin_dir}/.claude-plugin/plugin.json",
                claude_plugin_json(),
            )
            for skill in injected_skills:
                container_manager.write_directory(
                    container_name,
                    f"{claude_plugin_dir}/skills/{skill.id}",
                    Path(skill.source_path),
                )
        except Exception as exc:
            errors.append(f"claude_plugin: failed to write session plugin: {exc}")
            claude_plugin_dir = ""

    rendered_instructions = instructions(
        mcp_path,
        skill_root,
        injected_mcp_servers,
        injected_skills,
        files_appendix=files_appendix,
    )
    return CapabilityInjection(
        instructions=rendered_instructions,
        summary=summary([item.id for item in injected_mcp_servers], [item.id for item in injected_skills], errors),
        mcp_servers=[item.id for item in injected_mcp_servers],
        skills=[item.id for item in injected_skills],
        errors=errors,
        context=WorkerExecutionContext(
            capability_root=capability_root if (injected_mcp_servers or injected_skills) else "",
            mcp_config_path=mcp_path if injected_mcp_servers else "",
            skill_root=skill_root if injected_skills else "",
            claude_plugin_dir=claude_plugin_dir if injected_skills and claude_plugin_dir else "",
            mcp_servers=injected_mcp_details,
            skills=[item.id for item in injected_skills],
        ),
    )


def _safe_path_segment(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    text = text.strip("._")
    return text or "unknown"
