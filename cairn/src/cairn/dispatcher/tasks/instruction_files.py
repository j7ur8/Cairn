from __future__ import annotations

import json
from dataclasses import dataclass

from cairn.dispatcher.capability_constants import CAPABILITY_ROOT
from cairn.dispatcher.runtime.docker_labels import safe_project_id
from cairn.dispatcher.tasks.context import ContainerRuntime
from cairn.dispatcher.workers.base import WorkerExecutionContext
from cairn.shared.contracts import ProjectDetail


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
    if project is not None:
        project_context = _project_context(project)
    else:
        project_context = _project_context_from_values(project_origin or "", project_goal or "")
    phase_context = _phase_context(task_type)
    capabilities_context = capability_instructions.strip() or "No MCP servers or skills are exposed for this task."
    policy = _policy(project_id, task_type, task_instance_id, context)
    instruction = _agent_instruction(
        task_type=task_type,
        role_instructions=role_instructions,
        phase_context_path=paths.phase_context_path,
        project_context_path=paths.project_context_path,
        capabilities_context_path=paths.capabilities_context_path,
        policy_path=paths.policy_path,
    )
    return paths, {
        paths.project_context_path: project_context,
        paths.phase_context_path: phase_context,
        paths.capabilities_context_path: capabilities_context,
        paths.policy_path: json.dumps(policy, ensure_ascii=False, indent=2),
        paths.claude_md_path: instruction,
        paths.agents_md_path: instruction,
    }


def _instruction_root(project_id: str, task_instance_id: str) -> str:
    return f"{CAPABILITY_ROOT}/{safe_project_id(project_id)}/{safe_project_id(task_instance_id)}/instructions"


def _project_context(project: ProjectDetail | None) -> str:
    facts = {fact.id: fact.description for fact in project.facts} if project is not None else {}
    return _project_context_from_values(facts.get("origin", ""), facts.get("goal", ""))


def _project_context_from_values(origin: str, goal: str) -> str:
    return "\n".join(
        [
            "# Project Context",
            "",
            "## Origin",
            "```",
            origin,
            "```",
            "",
            "## Goal",
            "```",
            goal,
            "```",
            "",
            "Hints are dynamic task input and are intentionally not stored in this instruction file.",
        ]
    )


def _phase_context(task_type: str) -> str:
    if task_type == "bootstrap":
        body = [
            "Bootstrap is target discovery and profiling only.",
            "Do not perform vulnerability probing, exploitation, brute force, high-volume enumeration, fuzzing, or exploit-chain payloading.",
            "Use only non-intrusive observations needed to identify the target, purpose, exposed entrypoints, technology, runtime fingerprints, access boundaries, supplied materials, and directly observable abnormal behavior.",
        ]
    elif task_type == "explore":
        body = [
            "Explore only the assigned Current Intent from the active task prompt.",
            "Stop when evidence is sufficient, the path is disproven, or the active phase boundary is reached.",
            "Do not broaden into adjacent intent families unless the active prompt and exposed capabilities explicitly require it.",
        ]
    elif task_type == "reason":
        body = [
            "Reason does not execute tools or continue exploration.",
            "Judge whether the confirmed graph satisfies the goal, needs new intents, or should wait for existing open intents.",
            "Use only the graph, hints, fact ids, open intents, and output schema in the active prompt.",
        ]
    else:
        body = ["Follow the active phase prompt and use only the tools exposed for this task."]
    return "# Phase Boundary\n\n" + "\n".join(f"- {line}" for line in body)


def _policy(project_id: str, task_type: str, task_instance_id: str, context: WorkerExecutionContext) -> dict[str, object]:
    return {
        "project_id": project_id,
        "task_type": task_type,
        "task_instance_id": task_instance_id,
        "read_only": task_type in {"reason", "bootstrap_conclude", "explore_conclude"},
        "allowed_mcp_ids": [item.get("id") for item in context.mcp_servers or [] if isinstance(item.get("id"), str)],
        "denied_tool_classes": _denied_tool_classes(task_type),
        "hooks_enabled": False,
    }


def _denied_tool_classes(task_type: str) -> list[str]:
    if task_type == "bootstrap":
        return ["exploit", "bruteforce", "fuzzing", "high_volume_scan", "metasploit"]
    if task_type == "reason":
        return ["bash", "write", "mcp", "browser", "network"]
    return []


def _agent_instruction(
    *,
    task_type: str,
    role_instructions: str,
    phase_context_path: str,
    project_context_path: str,
    capabilities_context_path: str,
    policy_path: str,
) -> str:
    lines = [
        "# Task Instructions",
        "",
        f"Current Cairn task phase: `{task_type}`.",
        "",
        "Read and follow these task-local context files:",
        f"- Project context: `{project_context_path}`",
        f"- Phase boundary: `{phase_context_path}`",
        f"- Capability summary: `{capabilities_context_path}`",
        f"- Machine-readable policy: `{policy_path}`",
        "",
        "The active task prompt is the authority for dynamic inputs, output markers, JSON schemas, current intent data, fact graph snapshots, and hints.",
        "Do not treat hints, graph snapshots, or output markers as long-lived instructions.",
        "Use only MCP servers and skills exposed for this task.",
        "If a capability is available but does not match the active prompt and phase boundary, do not use it.",
    ]
    role = role_instructions.strip()
    if role:
        lines.extend(["", "## Project Role", role])
    return "\n".join(lines) + "\n"
