from __future__ import annotations

import json
import logging
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cairn.dispatcher.config import DispatchConfig, McpServerCapabilityConfig, SkillCapabilityConfig, TaskType
from cairn.dispatcher.workers.base import WorkerExecutionContext

if TYPE_CHECKING:
    from cairn.dispatcher.runtime.containers import ContainerManager

CAPABILITY_ROOT = "/tmp/cairn-capabilities"
CHROME_DEVTOOLS_PROBE_TYPE = "chrome_devtools_http"
HOST_DOCKER_INTERNAL = "host.docker.internal"
CLAUDE_SESSION_PLUGIN_NAME = "cairn-session-capabilities"
LOG = logging.getLogger(__name__)


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
                "detail": item.transport,
                "source_path": item.source_path,
                "transport": item.transport,
                "command": item.command,
                "args": _runtime_mcp_args(item, ""),
                "url": item.url,
                "bearer_token_env": item.bearer_token_env,
                "headers": {},
                "probe_config": dict(item.probe_config),
                # Skills the dispatcher must auto-inject when this MCP
                # is selected. Carried through the catalog register
                # call so the server can persist it and the expansion
                # layer can use it on every project save.
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

    tasks = selection_data.get("tasks") if isinstance(selection_data.get("tasks"), dict) else {}
    task_state = tasks.get(task_type) if isinstance(tasks.get(task_type), dict) else {}
    snapshots = task_state.get("snapshots") if isinstance(task_state.get("snapshots"), list) else []
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
    errors: list[str] = []

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
        probe_error = _validate_selected_mcp(item, task_type)
        if probe_error:
            errors.append(probe_error)
            continue
        mcp_servers.append(item)

    skills: list[SkillCapabilityConfig] = []
    for capability_id in selected_skills:
        item = skill_by_id.get(capability_id)
        if item is None:
            errors.append(f"skill:{capability_id}: not declared in dispatch config")
            continue
        if task_type not in item.task_types:
            LOG.info(
                "skip skill=%s because task_type=%s is not enabled enabled_task_types=%s",
                capability_id,
                task_type,
                item.task_types,
            )
            continue
        skills.append(item)

    if not mcp_servers and not skills:
        return CapabilityInjection("", _summary([], [], errors), [], [], errors, WorkerExecutionContext())

    if task_type == "reason":
        instructions = _reason_instructions(mcp_servers, skills)
        return CapabilityInjection(
            instructions=instructions,
            summary=_summary([item.id for item in mcp_servers], [item.id for item in skills], errors),
            mcp_servers=[item.id for item in mcp_servers],
            skills=[item.id for item in skills],
            errors=errors,
            context=WorkerExecutionContext(),
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
    if injected_skills:
        try:
            container_manager.write_text_file(
                container_name,
                f"{claude_plugin_dir}/.claude-plugin/plugin.json",
                _claude_plugin_json(),
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
            claude_plugin_dir=claude_plugin_dir if injected_skills and claude_plugin_dir else "",
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


def _claude_plugin_json() -> str:
    payload = {
        "name": CLAUDE_SESSION_PLUGIN_NAME,
        "version": "0.0.0",
        "description": "Session-only Cairn capability skills for the current task.",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _mcp_config_detail(item: McpServerCapabilityConfig, capability_root: str) -> dict[str, Any]:
    """Render the per-server entry in the mcp.json file.

    For ``stdio``: emit ``{command, args, env}`` (Claude Code / Codex will
    fork the subprocess). For ``http``: emit ``{type: "http", url, headers}``
    with the bearer token resolved inline (Claude Code does not dereference
    env vars in mcp.json headers). The token is read from the dispatcher's
    ``os.environ`` at call time and is not cached on the config object.
    """
    if item.transport == "http":
        detail: dict[str, Any] = {"type": "http", "url": _render_capability_path(item.url, capability_root)}
        if item.bearer_token_env:
            token = os.environ.get(item.bearer_token_env)
            if token:
                # Read the token here, inline; do not store on the item. The
                # returned dict is consumed immediately by json.dumps in
                # _mcp_json and released after the task ends.
                detail["headers"] = {"Authorization": f"Bearer {token}"}
        return detail
    return {
        "command": _render_capability_path(item.command, capability_root),
        "args": _runtime_mcp_args(item, capability_root),
        "env": {key: _render_capability_path(value, capability_root) for key, value in item.env.items()},
    }


def _mcp_detail(item: McpServerCapabilityConfig, capability_root: str) -> dict[str, Any]:
    """Adapter-facing context detail.

    Contains only the schema-level fields the worker adapter needs to
    construct its argv. The resolved bearer token (if any) is intentionally
    NOT included — it lives in mcp.json's ``headers`` only, and is read
    at mcp.json write time via ``_mcp_config_detail``. The adapter either
    uses ``bearer_token_env`` to ask the agent to read the env (Codex) or
    does not need a token at all (Claude reads mcp.json directly).
    """
    detail: dict[str, Any] = {
        "id": item.id,
        "transport": item.transport,
    }
    if item.transport == "http":
        detail["url"] = _render_capability_path(item.url, capability_root)
        if item.bearer_token_env:
            detail["bearer_token_env"] = item.bearer_token_env
    else:
        detail["command"] = _render_capability_path(item.command, capability_root)
        if item.args:
            detail["args"] = _runtime_mcp_args(item, capability_root)
        if item.env:
            detail["env"] = {
                key: _render_capability_path(value, capability_root)
                for key, value in item.env.items()
            }
    return detail


def _render_capability_path(value: str, capability_root: str) -> str:
    return value.replace("{capability_root}", capability_root)


def _is_chrome_devtools_probe(probe_config: dict[str, Any] | None) -> bool:
    if not isinstance(probe_config, dict):
        return False
    return str(probe_config.get("type") or "").strip() == CHROME_DEVTOOLS_PROBE_TYPE


def _host_netloc(host: str, port: int | None) -> str:
    netloc_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"{netloc_host}:{port}" if port is not None else netloc_host


def _resolve_host_alias_url(url: str) -> tuple[str, str | None]:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    if not host or host.lower() != HOST_DOCKER_INTERNAL:
        return url, None
    try:
        resolved = socket.gethostbyname(host)
    except OSError as exc:
        return url, f"resolve {host} failed: {type(exc).__name__}: {exc}"
    netloc = _host_netloc(resolved, parsed.port)
    return urllib.parse.urlunparse(parsed._replace(netloc=netloc)), None


def _chrome_devtools_probe_url(probe_config: dict[str, Any]) -> tuple[str, str | None]:
    url = str(probe_config.get("url") or "").strip()
    if not url:
        return "", "chrome devtools probe missing url"
    return _resolve_host_alias_url(url)


def _runtime_mcp_args(item: McpServerCapabilityConfig, capability_root: str) -> list[str]:
    args = [_render_capability_path(arg, capability_root) for arg in item.args]
    if not _is_chrome_devtools_probe(item.probe_config):
        return args
    return _rewrite_chrome_devtools_browser_args(args)


def _rewrite_chrome_devtools_browser_args(args: list[str]) -> list[str]:
    out: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("--browserUrl", "--browser-url", "-u") and index + 1 < len(args):
            resolved, _ = _resolve_host_alias_url(args[index + 1])
            out.append("--browserUrl" if arg == "--browser-url" else arg)
            out.append(resolved)
            index += 2
            continue
        if arg.startswith("--browserUrl=") or arg.startswith("--browser-url="):
            prefix = "--browserUrl="
            value = arg.split("=", 1)[1]
            resolved, _ = _resolve_host_alias_url(value)
            out.append(f"{prefix}{resolved}")
            index += 1
            continue
        out.append(arg)
        index += 1
    return out


def _probe_http_url(url: str, timeout: float) -> tuple[bool, str]:
    """Best-effort reachability probe for an http MCP server.

    Does a TCP connect to (host, port) so the probe does not depend on
    path correctness, auth, or the upstream agent's HTTP semantics. Any
    successful connect (including a 4xx/5xx from the server) is treated
    as "reachable". Returns ``(ok, reason)``.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False, "url has no host"
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except (OSError, socket.timeout) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _probe_http_json_key(url: str, timeout: float, required_key: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if not 200 <= status < 400:
                return False, f"http {status}"
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        reason = f"http {exc.code}: {exc.reason}"
        if exc.code == 500:
            reason += " (Chrome DevTools may reject the Host header or require --remote-debugging-address=0.0.0.0)"
        return False, reason
    except Exception as exc:  # noqa: BLE001 - best-effort validation
        return False, f"{type(exc).__name__}: {exc}"
    value = payload.get(required_key) if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value.strip():
        return False, f"missing json key: {required_key}"
    return True, ""


def _probe_config_error(mcp: McpServerCapabilityConfig) -> str | None:
    if not _is_chrome_devtools_probe(mcp.probe_config):
        return None
    url, resolve_error = _chrome_devtools_probe_url(mcp.probe_config)
    if resolve_error:
        return f"mcp_server:{mcp.id}: {resolve_error}"
    ok, reason = _probe_http_json_key(
        url,
        mcp.healthcheck_timeout,
        "webSocketDebuggerUrl",
    )
    if not ok:
        return f"mcp_server:{mcp.id}: chrome devtools probe failed: {reason}"
    return None



def _validate_selected_mcp(
    mcp: McpServerCapabilityConfig,
    task_type: TaskType,
) -> str | None:
    """Per-task healthcheck for a selected MCP. Returns an error string or None."""
    probe_error = _probe_config_error(mcp)
    if probe_error:
        return probe_error
    if mcp.transport == "http" and mcp.url:
        ok, reason = _probe_http_url(mcp.url, mcp.healthcheck_timeout)
        if not ok:
            return f"mcp_server:{mcp.id}: http probe failed: {reason}"
    return None


def _instructions(
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


def _reason_instructions(
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
