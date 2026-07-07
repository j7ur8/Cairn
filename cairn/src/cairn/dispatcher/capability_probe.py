from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from cairn.dispatcher.capability_url import is_chrome_devtools_probe, resolve_host_alias_url
from cairn.shared.config import McpServerCapabilityConfig, TaskType


def chrome_devtools_probe_url(probe_config: dict[str, Any]) -> tuple[str, str | None]:
    url = str(probe_config.get("url") or "").strip()
    if not url:
        return "", "chrome devtools probe missing url"
    return resolve_host_alias_url(url)


def probe_http_url(url: str, timeout: float) -> tuple[bool, str]:
    """Best-effort reachability probe for an http MCP server."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    if not host:
        return False, "url has no host"
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except (TimeoutError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def probe_http_json_key(url: str, timeout: float, required_key: str) -> tuple[bool, str]:
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


def probe_config_error(mcp: McpServerCapabilityConfig) -> str | None:
    if not is_chrome_devtools_probe(mcp.probe_config):
        return None
    url, resolve_error = chrome_devtools_probe_url(mcp.probe_config)
    if resolve_error:
        return f"mcp_server:{mcp.id}: {resolve_error}"
    ok, reason = probe_http_json_key(
        url,
        mcp.healthcheck_timeout,
        "webSocketDebuggerUrl",
    )
    if not ok:
        return f"mcp_server:{mcp.id}: chrome devtools probe failed: {reason}"
    return None


def validate_selected_mcp(
    mcp: McpServerCapabilityConfig,
    task_type: TaskType,
) -> str | None:
    """Per-task healthcheck for a selected MCP. Returns an error string or None."""
    probe_error = probe_config_error(mcp)
    if probe_error:
        return probe_error
    if mcp.transport == "http" and mcp.url and "{" not in mcp.url:
        ok, reason = probe_http_url(mcp.url, mcp.healthcheck_timeout)
        if not ok:
            return f"mcp_server:{mcp.id}: http probe failed: {reason}"
    return None
