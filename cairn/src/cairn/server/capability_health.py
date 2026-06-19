"""Capability health probes."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from cairn.server.capability_expansion import TASK_TYPES, CatalogEntry, catalog_map_from_items
from cairn.server.config.capabilities import update_yaml_mcp_probe_results
from cairn.server.schemas import CapabilityHealthEntry, TaskCapabilities, TaskCapabilitiesMap

PROBE_TIMEOUT_SECONDS = 1.5
CHROME_DEVTOOLS_PROBE_TYPE = "chrome_devtools_http"
HOST_DOCKER_INTERNAL = "host.docker.internal"


def _probe_http_json_key(url: str, required_key: str) -> CapabilityHealthEntry | None:
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT_SECONDS) as resp:
            ok = 200 <= resp.status < 400
            if not ok:
                return CapabilityHealthEntry(
                    capability_id="",
                    status="warn",
                    message=f"http {resp.status}",
                )
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = f"http {exc.code}: {exc.reason}"
        if exc.code == 500:
            message += " (Chrome DevTools may reject the Host header or require --remote-debugging-address=0.0.0.0)"
        return CapabilityHealthEntry(
            capability_id="",
            status="error",
            message=message,
        )
    except Exception as exc:  # noqa: BLE001 - probe best-effort
        return CapabilityHealthEntry(
            capability_id="",
            status="error",
            message=str(exc),
        )
    value = payload.get(required_key) if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value.strip():
        return CapabilityHealthEntry(
            capability_id="",
            status="error",
            message=f"missing json key: {required_key}",
        )
    return None


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


def probe_mcp(entry: CatalogEntry) -> CapabilityHealthEntry:
    probe_type = str(entry.item.probe_config.get("type") or "").strip()
    if probe_type == CHROME_DEVTOOLS_PROBE_TYPE:
        url = str(entry.item.probe_config.get("url") or "").strip()
        if not url:
            return CapabilityHealthEntry(
                capability_id=entry.item.id, status="warn", message="chrome devtools probe missing url",
            )
        url, resolve_error = _resolve_host_alias_url(url)
        if resolve_error:
            return CapabilityHealthEntry(
                capability_id=entry.item.id, status="error", message=resolve_error,
            )
        result = _probe_http_json_key(url, "webSocketDebuggerUrl")
        if result is None:
            return CapabilityHealthEntry(
                capability_id=entry.item.id, status="ok", message="chrome devtools endpoint reachable",
            )
        result.capability_id = entry.item.id
        return result
    if entry.transport == "http" and entry.url:
        try:
            with urllib.request.urlopen(
                entry.url, timeout=PROBE_TIMEOUT_SECONDS
            ) as resp:
                ok = 200 <= resp.status < 400
                return CapabilityHealthEntry(
                    capability_id=entry.item.id,
                    status="ok" if ok else "warn",
                    message=f"http {resp.status}",
                )
        except Exception as exc:  # noqa: BLE001 - probe best-effort
            return CapabilityHealthEntry(
                capability_id=entry.item.id, status="error", message=str(exc),
            )
    if entry.transport == "stdio":
        if entry.source_path:
            path = Path(entry.source_path)
            if not path.exists():
                return CapabilityHealthEntry(
                    capability_id=entry.item.id, status="error",
                    message=f"stdio path missing: {path}",
                )
            return CapabilityHealthEntry(
                capability_id=entry.item.id, status="ok", message="stdio path present",
            )
        if entry.command:
            return CapabilityHealthEntry(
                capability_id=entry.item.id, status="ok", message="stdio command configured",
            )
        return CapabilityHealthEntry(
            capability_id=entry.item.id, status="warn", message="no probe config"
        )
    return CapabilityHealthEntry(
        capability_id=entry.item.id, status="warn", message="no probe config"
    )


def probe_skill(entry: CatalogEntry) -> CapabilityHealthEntry:
    if not entry.source_path:
        return CapabilityHealthEntry(
            capability_id=entry.item.id, status="warn",
            message="no source_path",
        )
    path = Path(entry.source_path)
    if not path.exists():
        return CapabilityHealthEntry(
            capability_id=entry.item.id, status="error",
            message=f"source_path missing: {path}",
        )
    skill_md = path / "SKILL.md"
    if not skill_md.exists():
        return CapabilityHealthEntry(
            capability_id=entry.item.id, status="warn",
            message="SKILL.md not present",
        )
    try:
        head = skill_md.read_text(encoding="utf-8", errors="replace")[:4096]
    except Exception as exc:  # noqa: BLE001
        return CapabilityHealthEntry(
            capability_id=entry.item.id, status="error",
            message=f"SKILL.md read failed: {exc}",
        )
    if not head.strip().startswith("#") and "name:" not in head:
        return CapabilityHealthEntry(
            capability_id=entry.item.id, status="warn",
            message="SKILL.md missing frontmatter or title",
        )
    return CapabilityHealthEntry(
        capability_id=entry.item.id, status="ok", message="skill manifest readable"
    )


def probe_capability(conn: Any, kind: str, capability_id: str) -> CapabilityHealthEntry:
    from cairn.server.config.capabilities import list_yaml_capabilities

    item = next((item for item in list_yaml_capabilities() if item.kind == kind and item.id == capability_id), None)
    if item is None:
        raise HTTPException(404, f"{kind} not found: {capability_id}")
    entry = catalog_map_from_items([item])[(kind, capability_id)]
    if kind == "mcp_server":
        return probe_mcp_via_dispatcher([capability_id])[0]
    if kind == "skill":
        return probe_skill(entry)
    raise HTTPException(400, f"unknown kind: {kind}")


def probe_all_mcp_via_dispatcher() -> list[CapabilityHealthEntry]:
    from cairn.server.config.capabilities import list_yaml_capabilities

    server_ids = [item.id for item in list_yaml_capabilities() if item.kind == "mcp_server"]
    return probe_mcp_via_dispatcher(server_ids)


def probe_mcp_via_dispatcher(server_ids: list[str]) -> list[CapabilityHealthEntry]:
    ids = _dedupe_ids(server_ids)
    if not ids:
        return []
    raw_results = _dispatcher_probe_request(ids)
    items = update_yaml_mcp_probe_results(raw_results)
    by_id = {item.id: item for item in items}
    out: list[CapabilityHealthEntry] = []
    for capability_id in ids:
        item = by_id.get(capability_id)
        if item is None:
            out.append(CapabilityHealthEntry(capability_id=capability_id, status="error", message="probe result missing"))
            continue
        out.append(CapabilityHealthEntry(
            capability_id=item.id,
            status=item.last_probe_status or "error",
            message=item.last_probe_message,
        ))
    return out


def _dispatcher_probe_request(server_ids: list[str]) -> list[dict[str, str]]:
    from cairn.server.runtime_config import system_config

    runtime = system_config()
    url = _dispatcher_probe_url(runtime.dispatcher.reload_url)
    body = json.dumps({"server_ids": server_ids}, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    token = runtime.auth.dispatcher_api_token
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        return [
            {
                "capability_id": capability_id,
                "status": "error",
                "message": f"dispatcher probe failed: HTTP {exc.code}: {detail}",
            }
            for capability_id in server_ids
        ]
    except Exception as exc:  # noqa: BLE001
        return [
            {
                "capability_id": capability_id,
                "status": "error",
                "message": f"dispatcher probe failed: {exc}",
            }
            for capability_id in server_ids
        ]
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return [
            {
                "capability_id": capability_id,
                "status": "error",
                "message": "dispatcher probe returned invalid response",
            }
            for capability_id in server_ids
        ]
    return [_normalize_dispatcher_probe_result(item) for item in results if isinstance(item, dict)]


def _dispatcher_probe_url(reload_url: str) -> str:
    parsed = urllib.parse.urlparse(reload_url)
    if parsed.path.endswith("/reload"):
        path = f"{parsed.path[:-len('/reload')]}/mcp-probe"
    else:
        path = "/mcp-probe"
    return urllib.parse.urlunparse(parsed._replace(path=path, params="", query="", fragment=""))


def _normalize_dispatcher_probe_result(item: dict[str, Any]) -> dict[str, str]:
    status = str(item.get("status") or "error")
    if status not in ("ok", "warn", "error"):
        status = "error"
    return {
        "capability_id": str(item.get("capability_id") or "").strip(),
        "status": status,
        "message": str(item.get("message") or "").strip(),
    }


def _dedupe_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = str(value or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def probe_per_task(
    conn: Any,
    per_task: TaskCapabilitiesMap,
    catalog: dict[tuple[str, str], CatalogEntry],
) -> dict[str, list[CapabilityHealthEntry]]:
    """Probe every chosen capability, grouped by task_type."""
    out: dict[str, list[CapabilityHealthEntry]] = {task: [] for task in TASK_TYPES}
    for task in TASK_TYPES:
        selection = per_task.get(task) or TaskCapabilities()
        ids = list(selection.mcp_server_ids) + list(selection.skill_ids)
        seen: set[str] = set()
        for cid in ids:
            if cid in seen:
                continue
            seen.add(cid)
            entry = catalog.get(("mcp_server", cid)) or catalog.get(("skill", cid))
            if entry is None:
                out[task].append(CapabilityHealthEntry(
                    capability_id=cid, status="warn", message="not in catalog"
                ))
                continue
            if entry.item.kind == "mcp_server":
                out[task].append(probe_mcp(entry))
            else:
                out[task].append(probe_skill(entry))
    return out
