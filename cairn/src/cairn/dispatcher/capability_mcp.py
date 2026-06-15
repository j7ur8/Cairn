from __future__ import annotations

import json
from typing import Any, overload

from cairn.dispatcher.capability_constants import CLAUDE_SESSION_PLUGIN_NAME
from cairn.dispatcher.capability_url import is_chrome_devtools_probe, resolve_host_alias_url
from cairn.shared.config import McpServerCapabilityConfig


def mcp_json(mcp_servers: list[McpServerCapabilityConfig], capability_root: str) -> str:
    payload = {
        "mcpServers": {
            item.id: mcp_config_detail(item, capability_root)
            for item in mcp_servers
        }
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def claude_plugin_json() -> str:
    payload = {
        "name": CLAUDE_SESSION_PLUGIN_NAME,
        "version": "0.0.0",
        "description": "Session-only Cairn capability skills for the current task.",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def mcp_config_detail(item: McpServerCapabilityConfig, capability_root: str) -> dict[str, Any]:
    """Render the per-server entry in the mcp.json file."""
    if item.transport == "http":
        detail: dict[str, Any] = {"type": "http", "url": render_capability_path(item.url, capability_root)}
        if item.headers:
            detail["headers"] = {
                key: render_capability_path(value, capability_root)
                for key, value in item.headers.items()
            }
        return detail
    return {
        "command": render_capability_path(item.command, capability_root),
        "args": runtime_mcp_args(item, capability_root),
        "env": {key: render_capability_path(value, capability_root) for key, value in item.env.items()},
    }


def mcp_detail(item: McpServerCapabilityConfig, capability_root: str) -> dict[str, Any]:
    """Adapter-facing context detail."""
    detail: dict[str, Any] = {
        "id": item.id,
        "transport": item.transport,
    }
    if item.transport == "http":
        detail["url"] = render_capability_path(item.url, capability_root)
        if item.headers:
            detail["headers"] = {
                key: render_capability_path(value, capability_root)
                for key, value in item.headers.items()
            }
    else:
        detail["command"] = render_capability_path(item.command, capability_root)
        if item.args:
            detail["args"] = runtime_mcp_args(item, capability_root)
        if item.env:
            detail["env"] = {
                key: render_capability_path(value, capability_root)
                for key, value in item.env.items()
            }
    return detail


@overload
def render_capability_path(value: str, capability_root: str) -> str: ...
@overload
def render_capability_path(value: None, capability_root: str) -> None: ...
def render_capability_path(value: str | None, capability_root: str) -> str | None:
    if value is None:
        return None
    return value.replace("{capability_root}", capability_root)


def runtime_mcp_args(item: McpServerCapabilityConfig, capability_root: str) -> list[str]:
    args = [render_capability_path(arg, capability_root) for arg in item.args]
    if not is_chrome_devtools_probe(item.probe_config):
        return args
    return rewrite_chrome_devtools_browser_args(args)


def rewrite_chrome_devtools_browser_args(args: list[str]) -> list[str]:
    out: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("--browserUrl", "--browser-url", "-u") and index + 1 < len(args):
            resolved, _ = resolve_host_alias_url(args[index + 1])
            out.append("--browserUrl" if arg == "--browser-url" else arg)
            out.append(resolved)
            index += 2
            continue
        if arg.startswith("--browserUrl=") or arg.startswith("--browser-url="):
            prefix = "--browserUrl="
            value = arg.split("=", 1)[1]
            resolved, _ = resolve_host_alias_url(value)
            out.append(f"{prefix}{resolved}")
            index += 1
            continue
        out.append(arg)
        index += 1
    return out
