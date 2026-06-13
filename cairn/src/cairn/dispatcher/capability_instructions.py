from __future__ import annotations

import json

from cairn.dispatcher.capability_constants import CLAUDE_SESSION_PLUGIN_NAME
from cairn.shared.config import McpServerCapabilityConfig, SkillCapabilityConfig


def instructions(
    mcp_path: str,
    skill_root: str,
    mcp_servers: list[McpServerCapabilityConfig],
    skills: list[SkillCapabilityConfig],
) -> str:
    lines = [
        "# Project Capabilities",
        "The following capabilities are enabled for this task. Use them when their routing metadata matches the current work; do not use a capability only because it is available.",
        "",
    ]
    if mcp_servers:
        lines.extend(["## MCP Servers", f"Config file: {mcp_path}", ""])
        for item in mcp_servers:
            lines.append(f"- {item.id}: {item.name}")
            _append_text(lines, "Description", item.description)
            _append_list(lines, "Use when", item.use_when)
            _append_list(lines, "Required skills", item.required_skill_ids)
            _append_text(lines, "Instruction", item.activation_hint)
            lines.append("")
    if skills:
        lines.extend(["## Skills", f"Directory root: {skill_root}", ""])
        lines.append("When your agent runtime exposes a native Skill tool and routing conditions match, invoke the matching skill first. If native skill invocation is unavailable, read the listed SKILL.md path for domain guidance. Treat procedures and examples as optional heuristics, adapting them to the current goal, evidence, scope, and constraints.")
        lines.append("")
        for item in skills:
            path = f"{skill_root}/{item.id}"
            lines.append(f"- {item.id}: {item.name}")
            lines.append(f"  Path: {path}")
            lines.append(f"  Claude native Skill name: {CLAUDE_SESSION_PLUGIN_NAME}:{item.id}")
            _append_text(lines, "Description", item.description)
            _append_list(lines, "Use when", item.use_when)
            _append_list(lines, "Preferred MCP servers", item.preferred_mcp_ids)
            if item.activation_hint:
                _append_text(lines, "Instruction", item.activation_hint)
            else:
                lines.append(f"  Instruction: When routing conditions match, read {path}/SKILL.md for domain guidance and adapt any procedures or examples to the current evidence, scope, and constraints.")
            lines.append("")
    lines.extend(
        [
            "Use these capabilities only for the current Cairn project/challenge.",
            "Do not treat capability availability as a solved fact.",
            "Only report findings that are verified against the challenge target.",
        ]
    )
    return "\n".join(lines)


def reason_instructions(
    mcp_servers: list[McpServerCapabilityConfig],
    skills: list[SkillCapabilityConfig],
) -> str:
    lines = [
        "# Project Capabilities",
        "Selected capability metadata is available for reason-stage intent design only.",
        "Do not execute tools, open MCP sessions, read skill directories, or treat capability availability as a solved fact.",
        "",
    ]
    if mcp_servers:
        lines.append("- MCP server metadata:")
        for item in mcp_servers:
            lines.append(f"  - {item.id}: {item.name}")
            _append_text(lines, "Description", item.description, indent="    ")
            _append_list(lines, "Use when", item.use_when, indent="    ")
            _append_list(lines, "Required skills", item.required_skill_ids, indent="    ")
            _append_text(lines, "Instruction", item.activation_hint, indent="    ")
        lines.append("")
    if skills:
        lines.append("- Skill metadata:")
        for item in skills:
            lines.append(f"  - {item.id}: {item.name}")
            _append_text(lines, "Description", item.description, indent="    ")
            _append_list(lines, "Use when", item.use_when, indent="    ")
            _append_list(lines, "Preferred MCP servers", item.preferred_mcp_ids, indent="    ")
            _append_text(lines, "Instruction", item.activation_hint, indent="    ")
        lines.append("")
    lines.extend(
        [
            "Use this metadata only to choose focused, non-overlapping next intents.",
            "Exploration and capability execution belong in explore tasks.",
        ]
    )
    return "\n".join(lines)


def summary(mcp_ids: list[str], skill_ids: list[str], errors: list[str]) -> str:
    return json.dumps(
        {"mcp_servers": mcp_ids, "skills": skill_ids, "errors": errors},
        ensure_ascii=False,
        indent=2,
    )


def _append_text(lines: list[str], label: str, value: str, indent: str = "  ") -> None:
    text = (value or "").strip()
    if text:
        lines.append(f"{indent}{label}: {text}")


def _append_list(lines: list[str], label: str, values: list[str], indent: str = "  ") -> None:
    items = [item.strip() for item in values if item.strip()]
    if not items:
        return
    lines.append(f"{indent}{label}:")
    for item in items:
        lines.append(f"{indent}  - {item}")
