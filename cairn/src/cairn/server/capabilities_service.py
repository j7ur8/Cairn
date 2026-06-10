"""Service layer for YAML-backed capability expansion and probes."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from cairn.server.models_pkg.capabilities import (
    CapabilityCatalogItem,
    CapabilityHealthEntry,
    CapabilitySelection,
    TaskCapabilities,
    TaskCapabilitySelectionMap,
    TaskCapabilitiesMap,
    task_capabilities_map,
)
from cairn.shared.task_types import builtin_task_type_names
from cairn.shared.capability_projection import project_capability_tasks_payload

TASK_TYPES: tuple[str, ...] = builtin_task_type_names()


def selected_capabilities_to_internal(
    selections: TaskCapabilitySelectionMap | None,
) -> TaskCapabilitiesMap:
    """Convert public explicit selections into the internal expansion shape."""
    out = task_capabilities_map(None)
    if not isinstance(selections, dict):
        return out
    for task in TASK_TYPES:
        selection = selections.get(task) or CapabilitySelection()
        out[task] = TaskCapabilities.model_construct(
            mcp_server_ids=list(selection.mcp_server_ids),
            skill_ids=list(selection.skill_ids),
            user_mcp_server_ids=list(selection.mcp_server_ids),
            user_skill_ids=list(selection.skill_ids),
            role_default_skill_ids=[],
        )
    return out

PROBE_TIMEOUT_SECONDS = 1.5
CHROME_DEVTOOLS_PROBE_TYPE = "chrome_devtools_http"
HOST_DOCKER_INTERNAL = "host.docker.internal"


@dataclass
class _CatalogEntry:
    item: CapabilityCatalogItem
    source_path: str | None
    transport: str | None
    command: str | None
    args: list[str]
    url: str | None
    headers: dict[str, str]


def catalog_map_from_items(items: list[CapabilityCatalogItem]) -> dict[tuple[str, str], _CatalogEntry]:
    return {
        (item.kind, item.id): _CatalogEntry(
            item=item,
            source_path=item.source_path,
            transport=item.transport,
            command=item.command,
            args=item.args,
            url=item.url,
            headers=item.headers,
        )
        for item in items
    }


def expand_task_capabilities(
    per_task: TaskCapabilitiesMap,
    catalog: dict[tuple[str, str], _CatalogEntry],
    role_default_skill_ids: list[str] | None = None,
) -> tuple[TaskCapabilitiesMap, list[str]]:
    """Validate ids and expand requires in-place.

    Returns the expanded map and a list of human-readable warnings for
    missing or unavailable ids; the caller surfaces them on the
    response but never fails the project create for them.
    """
    errors: list[str] = []
    expanded: TaskCapabilitiesMap = {}
    for task in TASK_TYPES:
        selection = per_task.get(task) or TaskCapabilities()
        mcp_ids = list(selection.user_mcp_server_ids or selection.mcp_server_ids)
        if selection.user_skill_ids:
            skill_ids = list(selection.user_skill_ids)
        elif selection.role_default_skill_ids:
            skill_ids = [
                sid for sid in selection.skill_ids
                if sid not in selection.role_default_skill_ids
            ]
        else:
            skill_ids = list(selection.skill_ids)
        user_mcp = list(mcp_ids)
        user_skill = list(skill_ids)
        role_default_skills = _role_default_skills_for_task(role_default_skill_ids or [], task, catalog)
        role_default_skills.extend(
            sid for sid in selection.role_default_skill_ids if sid not in role_default_skills
        )

        # Validate primary ids. Keep the error per id rather than the
        # whole task so the UI can highlight just the bad rows.
        keep_mcp: list[str] = []
        for cid in mcp_ids:
            entry = catalog.get(("mcp_server", cid))
            if entry is None:
                errors.append(f"{task}: mcp_server {cid} not in catalog")
                continue
            if not entry.item.available:
                errors.append(f"{task}: mcp_server {cid} is unavailable")
                continue
            if task not in entry.item.task_types:
                errors.append(
                    f"{task}: mcp_server {cid} does not enable task_type={task}"
                )
                continue
            keep_mcp.append(cid)
        keep_skill: list[str] = []
        for cid in list(dict.fromkeys(skill_ids + role_default_skills)):
            entry = catalog.get(("skill", cid))
            if entry is None:
                errors.append(f"{task}: skill {cid} not in catalog")
                continue
            if not entry.item.available:
                errors.append(f"{task}: skill {cid} is unavailable")
                continue
            if task not in entry.item.task_types:
                errors.append(
                    f"{task}: skill {cid} does not enable task_type={task}"
                )
                continue
            keep_skill.append(cid)

        # Expand MCP -> required_skill_ids. Each kept MCP can declare
        # skills that the agent must load alongside it. Mirrors the
        # sub-skill walk below: same dedupe, same task_type gating.
        # Required skills that the user already picked are NOT in
        # auto_added (they keep source = "selected"); the user_pick
        # path owns them.
        mcp_required_auto: list[str] = []
        mcp_required_seen: set[str] = set()
        for mid in keep_mcp:
            entry = catalog.get(("mcp_server", mid))
            if entry is None:
                continue
            for sid in entry.item.required_skill_ids:
                if sid in keep_skill or sid in mcp_required_auto or sid in mcp_required_seen:
                    continue
                if sid in keep_skill:
                    # User already picked it: leave source = "selected".
                    mcp_required_seen.add(sid)
                    continue
                skill_entry = catalog.get(("skill", sid))
                if skill_entry is None or not skill_entry.item.available:
                    continue
                if task not in skill_entry.item.task_types:
                    continue
                mcp_required_auto.append(sid)
                mcp_required_seen.add(sid)

        # Expand sub-skill requires transitively. Sub-skills are NOT
        # validated against the task_type whitelist: the user picked
        # the parent, so a requires-link that targets a skill only
        # enabled for a sibling task is operator intent, not a bug.
        # Seed the queue with both user_picked skills AND
        # MCP-required skills, so the closure walks through both
        # dependency edges uniformly.
        auto_added: list[str] = list(mcp_required_auto)
        visited: set[str] = set(mcp_required_seen)
        queue: list[str] = list(keep_skill) + [s for s in mcp_required_auto]
        while queue:
            sid = queue.pop()
            if sid in visited:
                continue
            visited.add(sid)
            entry = catalog.get(("skill", sid))
            if entry is None:
                continue
            for child in entry.item.requires_ids:
                if child in keep_skill or child in auto_added:
                    continue
                # Same task_type gating as the user picks: the child
                # must be enabled for the current task_type. This keeps
                # the per-task invariance even with sub-skill expansion.
                child_entry = catalog.get(("skill", child))
                if child_entry is None or not child_entry.item.available:
                    continue
                if task not in child_entry.item.task_types:
                    continue
                auto_added.append(child)
                queue.append(child)

        # model_construct skips Pydantic validators; we already
        # separated user picks from auto-required skills.
        expanded[task] = TaskCapabilities.model_construct(
            mcp_server_ids=list(dict.fromkeys(keep_mcp)),
            skill_ids=list(dict.fromkeys(keep_skill + auto_added)),
            user_mcp_server_ids=user_mcp,
            user_skill_ids=user_skill,
            role_default_skill_ids=[
                sid for sid in role_default_skills
                if sid in keep_skill or sid in auto_added
            ],
        )
    return expanded, errors


def _role_default_skills_for_task(
    skill_ids: list[str],
    task: str,
    catalog: dict[tuple[str, str], _CatalogEntry],
) -> list[str]:
    out: list[str] = []
    for sid in skill_ids:
        if sid in out:
            continue
        entry = catalog.get(("skill", sid))
        if entry is None or not entry.item.available:
            continue
        if task not in entry.item.task_types:
            continue
        out.append(sid)
    return out


def project_capability_tasks(per_task: TaskCapabilitiesMap) -> dict[str, Any]:
    from cairn.server.models_pkg.capabilities import ProjectCapabilityTaskState

    return {
        task: ProjectCapabilityTaskState.model_validate(payload)
        for task, payload in project_capability_tasks_payload(per_task).items()
    }


def unavailable_capabilities(
    catalog: list[CapabilityCatalogItem],
    per_task: TaskCapabilitiesMap,
) -> dict[str, list[str]]:
    available_ids = {(item.kind, item.id) for item in catalog if item.available}
    unavailable_mcp: list[str] = []
    unavailable_skill: list[str] = []
    for selection in per_task.values():
        for cid in selection.mcp_server_ids:
            if ("mcp_server", cid) not in available_ids:
                unavailable_mcp.append(cid)
        for cid in selection.skill_ids:
            if ("skill", cid) not in available_ids:
                unavailable_skill.append(cid)
    return {
        "mcp_server_ids": sorted(set(unavailable_mcp)),
        "skill_ids": sorted(set(unavailable_skill)),
    }


# ---------------------------------------------------------------------------
# Health probes
# ---------------------------------------------------------------------------


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


def _probe_mcp(entry: _CatalogEntry) -> CapabilityHealthEntry:
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
            parsed = urllib.parse.urlparse(entry.url)
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


def _probe_skill(entry: _CatalogEntry) -> CapabilityHealthEntry:
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
        return _probe_mcp(entry)
    if kind == "skill":
        return _probe_skill(entry)
    raise HTTPException(400, f"unknown kind: {kind}")


def probe_per_task(
    conn: Any,
    per_task: TaskCapabilitiesMap,
    catalog: dict[tuple[str, str], _CatalogEntry],
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
                out[task].append(_probe_mcp(entry))
            else:
                out[task].append(_probe_skill(entry))
    return out
