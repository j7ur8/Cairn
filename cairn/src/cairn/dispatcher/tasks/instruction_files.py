from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cairn.dispatcher.prompts as prompt_package
from cairn.dispatcher.capability_constants import CAPABILITY_ROOT
from cairn.dispatcher.runtime.docker_labels import safe_project_id
from cairn.dispatcher.tasks.context import ContainerRuntime
from cairn.dispatcher.workers.base import WorkerExecutionContext
from cairn.shared.contracts import ProjectDetail

RUNTIME_INSTRUCTION_PHASES = ("bootstrap", "reason", "explore")
RUNTIME_INSTRUCTION_TEMPLATE_PATHS = (
    "AGENTS.md",
    "CLAUDE.md",
    "context/project.md",
    "context/phase.md",
    "context/capabilities.md",
    "context/policy.json",
)


@dataclass(slots=True)
class TaskInstructionPaths:
    instruction_root: str
    project_context_path: str
    phase_context_path: str
    capabilities_context_path: str
    policy_path: str
    claude_md_path: str
    agents_md_path: str


def inject_task_instructions(
    *,
    container_manager: ContainerRuntime,
    container_name: str,
    project: ProjectDetail | None,
    project_id: str,
    task_type: str,
    task_instance_id: str,
    role_instructions: str,
    capability_instructions: str,
    context: WorkerExecutionContext,
) -> TaskInstructionPaths:
    paths, files = render_task_instruction_files(
        project=project,
        project_id=project_id,
        task_type=task_type,
        task_instance_id=task_instance_id,
        role_instructions=role_instructions,
        capability_instructions=capability_instructions,
        context=context,
    )
    for path, content in files.items():
        container_manager.write_text_file(container_name, path, content)
    context.task_workspace = paths.instruction_root
    context.instruction_root = paths.instruction_root
    context.claude_md_path = paths.claude_md_path
    context.agents_md_path = paths.agents_md_path
    context.policy_path = paths.policy_path
    if not context.capability_root:
        context.capability_root = paths.instruction_root
    return paths


def render_task_instruction_files(
    *,
    project: ProjectDetail | None,
    project_id: str,
    task_type: str,
    task_instance_id: str,
    role_instructions: str,
    capability_instructions: str,
    context: WorkerExecutionContext,
    instruction_root: str | None = None,
    project_origin: str | None = None,
    project_goal: str | None = None,
) -> tuple[TaskInstructionPaths, dict[str, str]]:
    root = instruction_root or _instruction_root(project_id, task_instance_id)
    paths = TaskInstructionPaths(
        instruction_root=root,
        project_context_path=f"{root}/context/project.md",
        phase_context_path=f"{root}/context/phase.md",
        capabilities_context_path=f"{root}/context/capabilities.md",
        policy_path=f"{root}/context/policy.json",
        claude_md_path=f"{root}/CLAUDE.md",
        agents_md_path=f"{root}/AGENTS.md",
    )
    phase = _runtime_template_phase(task_type)
    if project is not None:
        project_origin, project_goal = _project_context_values(project)
    else:
        project_origin, project_goal = project_origin or "", project_goal or ""
    selected_mcp_ids = _selected_mcp_ids(context)
    values = {
        "project_id": project_id,
        "project_safe_id": safe_project_id(project_id),
        "task_instance_id": task_instance_id,
        "task_type": task_type,
        "origin": project_origin,
        "goal": project_goal,
        "selected role prompt": role_instructions.strip(),
        "selected_mcp_ids": capability_instructions.strip() or "No MCP servers or skills are exposed for this task.",
        "selected_mcp_ids_json": json.dumps(selected_mcp_ids, ensure_ascii=False),
        "project_context_path": paths.project_context_path,
        "phase_context_path": paths.phase_context_path,
        "capabilities_context_path": paths.capabilities_context_path,
        "policy_path": paths.policy_path,
        "read_only": json.dumps(task_type in {"reason", "bootstrap_conclude", "explore_conclude"}),
        "denied_tool_classes": json.dumps(_denied_tool_classes(task_type), ensure_ascii=False),
        "hooks_enabled": json.dumps(False),
    }
    rendered = {
        path: _render_runtime_instruction_template(phase, path, values)
        for path in RUNTIME_INSTRUCTION_TEMPLATE_PATHS
    }
    return paths, _absolute_instruction_files(paths, rendered)


def runtime_instruction_templates_root() -> Path:
    package_paths = list(getattr(prompt_package, "__path__", []))
    if len(package_paths) != 1:
        raise RuntimeError("prompt resources are not writable files")
    return (Path(package_paths[0]) / "runtime_instructions").resolve()


def runtime_instruction_template_path(phase: str, relative_path: str) -> Path:
    phase = validate_runtime_instruction_phase(phase)
    relative_path = validate_runtime_instruction_template_path(relative_path)
    root = runtime_instruction_templates_root()
    target = (root / phase / Path(relative_path)).resolve()
    if not target.is_relative_to(root / phase):
        raise ValueError("invalid runtime instruction template path")
    if not target.is_file():
        raise FileNotFoundError(relative_path)
    return target


def validate_runtime_instruction_phase(phase: str) -> str:
    if phase not in RUNTIME_INSTRUCTION_PHASES:
        raise ValueError("invalid runtime instruction phase")
    return phase


def validate_runtime_instruction_template_path(relative_path: str) -> str:
    parts = relative_path.split("/")
    if (
        not relative_path
        or relative_path.startswith("/")
        or "\\" in relative_path
        or parts != [part for part in parts if part]
        or ".." in parts
        or relative_path not in RUNTIME_INSTRUCTION_TEMPLATE_PATHS
    ):
        raise ValueError("invalid runtime instruction template path")
    return relative_path


def _absolute_instruction_files(paths: TaskInstructionPaths, rendered: dict[str, str]) -> dict[str, str]:
    return {
        paths.agents_md_path: rendered["AGENTS.md"],
        paths.claude_md_path: rendered["CLAUDE.md"],
        paths.project_context_path: rendered["context/project.md"],
        paths.phase_context_path: rendered["context/phase.md"],
        paths.capabilities_context_path: rendered["context/capabilities.md"],
        paths.policy_path: rendered["context/policy.json"],
    }


def _runtime_template_phase(task_type: str) -> str:
    if task_type in RUNTIME_INSTRUCTION_PHASES:
        return task_type
    return "explore"


def _render_runtime_instruction_template(phase: str, relative_path: str, values: dict[str, Any]) -> str:
    content = runtime_instruction_template_path(phase, relative_path).read_text(encoding="utf-8")
    for key, value in values.items():
        content = content.replace("{" + key + "}", str(value))
    return content


def _selected_mcp_ids(context: WorkerExecutionContext) -> list[str]:
    return [item.get("id") for item in context.mcp_servers or [] if isinstance(item.get("id"), str)]


def _project_context_values(project: ProjectDetail) -> tuple[str, str]:
    facts = {fact.id: fact.description for fact in project.facts}
    return facts.get("origin", ""), facts.get("goal", "")


def _instruction_root(project_id: str, task_instance_id: str) -> str:
    return f"{CAPABILITY_ROOT}/{safe_project_id(project_id)}/{safe_project_id(task_instance_id)}/instructions"


def _denied_tool_classes(task_type: str) -> list[str]:
    if task_type == "bootstrap":
        return ["exploit", "bruteforce", "fuzzing", "high_volume_scan", "metasploit"]
    if task_type == "reason":
        return ["bash", "write", "mcp", "browser", "network"]
    return []
