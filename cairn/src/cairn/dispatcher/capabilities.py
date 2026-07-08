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
from cairn.dispatcher.prompt_resources import load_prompt_files_appendix
from cairn.dispatcher.runtime.browser_provider import BrowserRuntimeContext, BrowserRuntimeLease, remove_temp_lease_file
from cairn.dispatcher.runtime.docker_labels import safe_project_id
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
    runtime_leases: list[BrowserRuntimeLease] | None = None

    def release_runtime_leases(self) -> None:
        for lease in self.runtime_leases or []:
            lease.release()
            remove_temp_lease_file(lease)


class CapabilityWriter(Protocol):
    def write_text_file(self, container_name: str, path: str, content: str) -> None: ...

    def write_directory(self, container_name: str, path: str, source: Path) -> None: ...


def inject_project_capabilities(
    config: DispatchConfig,
    client: Any | None,
    container_manager: CapabilityWriter,
    container_name: str,
    project_id: str,
    task_type: TaskType,
    task_instance_id: str,
    selection_data: dict[str, Any] | None,
    browser_runtime: BrowserRuntimeContext | None = None,
    tool_sidecar_manager: Any | None = None,
) -> CapabilityInjection:
    if task_type == "reason":
        return CapabilityInjection("", "", [], [], [], WorkerExecutionContext())

    include_files_appendix = task_type != "reason"
    files_errors: list[str] = []
    files_appendix = ""
    if include_files_appendix:
        files_appendix, files_errors = load_prompt_files_appendix(task_type)
    resources_appendix = ""

    def render_files_only_instructions() -> str:
        if not files_appendix.strip() and not resources_appendix.strip():
            return ""
        return instructions(
            "",
            "",
            [],
            [],
            files_appendix=files_appendix,
            resources_appendix=resources_appendix,
        )

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
    mcp_by_id, skill_by_id = _capability_catalog_from_selection(config, selection_data)
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
    runtime_replacements = {
        "project_id": project_id,
        "project_safe_id": safe_project_id(project_id),
        "task_instance_id": task_instance_id,
    }
    mcp_root = f"{capability_root}/mcp"
    mcp_path = f"{capability_root}/mcp.json"
    skill_root = f"{capability_root}/skills"
    claude_plugin_dir = f"{capability_root}/claude-plugin"
    injected_mcp_servers = _task_scoped_mcp_servers(mcp_servers, task_type)
    injected_skills: list[SkillCapabilityConfig] = []
    injected_mcp_details: list[dict[str, Any]] = []
    runtime_leases: dict[str, BrowserRuntimeLease] = {}
    if browser_runtime is not None:
        browser_runtime.lease_root = f"{capability_root}/leases"
    if mcp_servers:
        for mcp in mcp_servers:
            if not mcp.source_path:
                continue
            try:
                container_manager.write_directory(container_name, f"{mcp_root}/{mcp.id}", Path(mcp.source_path))
            except Exception as exc:
                errors.append(f"mcp_server:{mcp.id}: failed to inject directory: {exc}")
                injected_mcp_servers = [item for item in injected_mcp_servers if item.id != mcp.id]
        if browser_runtime is not None:
            for mcp in list(injected_mcp_servers):
                try:
                    lease = browser_runtime.acquire(mcp)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"mcp_server:{mcp.id}: runtime provider failed: {exc}")
                    injected_mcp_servers = [item for item in injected_mcp_servers if item.id != mcp.id]
                    continue
                if lease is not None:
                    runtime_leases[mcp.id] = lease
        for mcp in list(injected_mcp_servers):
            tool = _tool_sidecar_for_mcp(mcp.id)
            if tool is None:
                continue
            if tool_sidecar_manager is None:
                errors.append(f"mcp_server:{mcp.id}: tool sidecar manager unavailable")
                injected_mcp_servers = [item for item in injected_mcp_servers if item.id != mcp.id]
                continue
            try:
                tool_sidecar_manager.ensure_running(project_id, tool)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"mcp_server:{mcp.id}: tool sidecar failed: {exc}")
                injected_mcp_servers = [item for item in injected_mcp_servers if item.id != mcp.id]
                continue
        try:
            container_manager.write_text_file(
                container_name,
                mcp_path,
                mcp_json(injected_mcp_servers, capability_root, runtime_replacements, runtime_leases),
            )
        except Exception as exc:
            errors.append(f"mcp_servers: failed to write config: {exc}")
            for lease in runtime_leases.values():
                lease.release()
                remove_temp_lease_file(lease)
            runtime_leases = {}
            injected_mcp_servers = []
        injected_mcp_details = [
            mcp_detail(item, capability_root, runtime_replacements, runtime_leases)
            for item in injected_mcp_servers
        ]
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
    resources_appendix = _resources_appendix(injected_mcp_servers, task_type)

    rendered_instructions = instructions(
        mcp_path,
        skill_root,
        injected_mcp_servers,
        injected_skills,
        files_appendix=files_appendix,
        resources_appendix=resources_appendix,
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
        runtime_leases=list(runtime_leases.values()),
    )


def _safe_path_segment(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    text = text.strip("._")
    return text or "unknown"


def _resources_appendix(mcp_servers: list[McpServerCapabilityConfig], task_type: TaskType) -> str:
    if not any(mcp.id == "cairn-resources" for mcp in mcp_servers):
        return ""
    if task_type == "bootstrap":
        return "\n".join(
            [
                "Use the injected cairn-resources MCP server in read-only mode to query Cairn resource state instead of relying on prompt summaries.",
                "Servers are global AI-accessible remote server capabilities; they are not automatically proxies or relays.",
                "For Servers, use servers.list only.",
                "For Project Proxy endpoints, use project_proxy.list_endpoints, project_proxy.resolve_chain, and project_proxy.explain_endpoint only.",
                "Do not infer that a Server is a proxy endpoint unless the Cairn Resources MCP data explicitly supports that relationship.",
            ]
        )
    return "\n".join(
        [
            "Use the injected cairn-resources MCP server to query Cairn resource state instead of relying on prompt summaries.",
            "Servers are global AI-accessible remote server capabilities; they are not automatically proxies or relays.",
            "For Servers, start with servers.list. Use servers.run_command only when the listed server matches the task and the action is authorized.",
            "For Project Proxy endpoints, start with project_proxy.list_endpoints. Use project_proxy.resolve_chain to inspect prerequisites and project_proxy.record_usage_result after usage attempts.",
            "Do not infer that a Server is a proxy endpoint unless the Cairn Resources MCP data explicitly supports that relationship.",
        ]
    )


def _task_scoped_mcp_servers(
    mcp_servers: list[McpServerCapabilityConfig],
    task_type: TaskType,
) -> list[McpServerCapabilityConfig]:
    scoped: list[McpServerCapabilityConfig] = []
    for mcp in mcp_servers:
        sidecar = _sidecar_mcp_override(mcp)
        if sidecar is not None:
            mcp = sidecar
        if task_type == "bootstrap" and mcp.id == "cairn-resources":
            scoped.append(mcp.model_copy(update={"env": {**mcp.env, "CAIRN_RESOURCES_READ_ONLY": "1"}}))
            continue
        scoped.append(mcp)
    return scoped


def _tool_sidecar_for_mcp(capability_id: str) -> str | None:
    if capability_id == "kali-server-mcp":
        return "kali"
    if capability_id == "metasploit-mcp":
        return "metasploit"
    return None


def _sidecar_mcp_override(mcp: McpServerCapabilityConfig) -> McpServerCapabilityConfig | None:
    if mcp.id == "kali-server-mcp":
        return mcp.model_copy(
            update={
                "transport": "http",
                "command": None,
                "args": [],
                "env": {},
                "url": "http://cairn-kali-{project_safe_id}:8765/mcp",
            }
        )
    if mcp.id == "metasploit-mcp":
        return mcp.model_copy(
            update={
                "transport": "http",
                "command": None,
                "args": [],
                "env": {},
                "url": "http://cairn-metasploit-{project_safe_id}:8775/mcp",
            }
        )
    return None


def _capability_catalog_from_selection(
    config: DispatchConfig,
    selection_data: dict[str, Any],
) -> tuple[dict[str, McpServerCapabilityConfig], dict[str, SkillCapabilityConfig]]:
    catalog_raw = selection_data.get("catalog")
    if not isinstance(catalog_raw, list):
        return (
            {item.id: item for item in config.capabilities.mcp_servers},
            {item.id: item for item in config.capabilities.skills},
        )
    mcp_by_id: dict[str, McpServerCapabilityConfig] = {}
    skill_by_id: dict[str, SkillCapabilityConfig] = {}
    for item in catalog_raw:
        if not isinstance(item, dict):
            continue
        try:
            if item.get("kind") == "mcp_server":
                mcp_by_id[str(item.get("id") or "")] = McpServerCapabilityConfig.model_validate(_mcp_config_payload(item))
            elif item.get("kind") == "skill":
                skill_by_id[str(item.get("id") or "")] = SkillCapabilityConfig.model_validate(_skill_config_payload(item))
        except Exception as exc:  # noqa: BLE001
            LOG.warning("execution config capability catalog item ignored id=%s error=%s", item.get("id"), exc)
    return mcp_by_id, skill_by_id


def _mcp_config_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    payload.pop("kind", None)
    payload.pop("source", None)
    payload.pop("requires_ids", None)
    payload.pop("preferred_mcp_ids", None)
    payload["transport"] = payload.get("transport") or "stdio"
    payload["name"] = payload.get("name") or payload.get("id") or ""
    if payload.get("transport") == "stdio":
        payload["command"] = payload.get("command") or "true"
    return payload


def _skill_config_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    payload.pop("kind", None)
    payload.pop("source", None)
    payload.pop("transport", None)
    payload.pop("command", None)
    payload.pop("args", None)
    payload.pop("env", None)
    payload.pop("url", None)
    payload.pop("headers", None)
    payload.pop("required_skill_ids", None)
    payload["name"] = payload.get("name") or payload.get("id") or ""
    payload["source_path"] = payload.get("source_path") or "."
    return payload
