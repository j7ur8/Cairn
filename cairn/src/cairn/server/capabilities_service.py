"""Service layer for the per-task capability catalog.

Centralizes the bits the routers used to inline: catalog row <-> Pydantic
model, requires expansion, lightweight probes, and per-task snapshot
persistence. Keeping it out of the router file makes the admin/CRUD
endpoints straightforward and gives the dispatcher a single helper to
read what the server has decided to inject for a given task.
"""
from __future__ import annotations

import json
import socket
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from fastapi import HTTPException

from cairn.server.models import (
    CapabilityAdminRequest,
    CapabilityCatalogItem,
    CapabilityHealthEntry,
    CapabilitySelection,
    TaskCapabilities,
    TaskCapabilitySelectionMap,
    TaskCapabilitiesMap,
    task_capabilities_map,
)
from cairn.server.services import utcnow

TASK_TYPES: tuple[str, ...] = ("bootstrap", "explore", "reason")


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
    bearer_token_env: str | None
    headers: dict[str, str]


def _row_to_entry(row: sqlite3.Row) -> _CatalogEntry:
    try:
        requires_ids = json.loads(row["requires_ids"] or "[]")
    except json.JSONDecodeError:
        requires_ids = []
    try:
        probe_config = json.loads(row["probe_config"] or "{}")
    except json.JSONDecodeError:
        probe_config = {}
    args_value = json.loads(row["args"] or "[]") if "args" in row.keys() and row["args"] else []
    headers_value = json.loads(row["headers"] or "{}") if "headers" in row.keys() and row["headers"] else {}
    try:
        required_skill_ids = json.loads(row["required_skill_ids"] or "[]")
    except json.JSONDecodeError:
        required_skill_ids = []
    try:
        use_when = json.loads(row["use_when"] or "[]")
    except json.JSONDecodeError:
        use_when = []
    try:
        preferred_mcp_ids = json.loads(row["preferred_mcp_ids"] or "[]")
    except json.JSONDecodeError:
        preferred_mcp_ids = []
    item = CapabilityCatalogItem(
        kind=row["kind"],
        id=row["id"],
        name=row["name"],
        description=row["description"],
        task_types=json.loads(row["task_types"] or "[]"),
        requires_ids=requires_ids,
        required_skill_ids=required_skill_ids,
        use_when=use_when,
        activation_hint=row["activation_hint"] if "activation_hint" in row.keys() else "",
        preferred_mcp_ids=preferred_mcp_ids,
        source=row["source"] if "source" in row.keys() else "builtin",
        probe_config=probe_config,
        available=bool(row["available"]),
        detail=row["detail"],
        source_path=row["source_path"] if "source_path" in row.keys() else None,
        transport=row["transport"] if "transport" in row.keys() else None,
        command=row["command"] if "command" in row.keys() else None,
        args=args_value,
        url=row["url"] if "url" in row.keys() else None,
        bearer_token_env=row["bearer_token_env"] if "bearer_token_env" in row.keys() else None,
        headers=headers_value,
        last_probe_status=row["last_probe_status"] if "last_probe_status" in row.keys() else None,
        last_probe_at=row["last_probe_at"] if "last_probe_at" in row.keys() else None,
        last_probe_message=row["last_probe_message"] if "last_probe_message" in row.keys() else "",
    )
    return _CatalogEntry(
        item=item,
        source_path=row["source_path"] if "source_path" in row.keys() else None,
        transport=row["transport"] if "transport" in row.keys() else None,
        command=row["command"] if "command" in row.keys() else None,
        args=json.loads(row["args"] or "[]") if "args" in row.keys() and row["args"] else [],
        url=row["url"] if "url" in row.keys() else None,
        bearer_token_env=row["bearer_token_env"] if "bearer_token_env" in row.keys() else None,
        headers=json.loads(row["headers"] or "{}") if "headers" in row.keys() and row["headers"] else {},
    )


_SELECT_COLUMNS = (
    "kind, id, name, description, task_types, available, detail, "
    "source, requires_ids, required_skill_ids, use_when, activation_hint, preferred_mcp_ids, "
    "probe_config, last_probe_status, last_probe_at, "
    "last_probe_message, source_path, transport, command, args, url, "
    "bearer_token_env, headers"
)


def list_catalog(conn: sqlite3.Connection) -> list[CapabilityCatalogItem]:
    rows = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM capability_catalog ORDER BY kind, id"
    ).fetchall()
    return [_row_to_entry(row).item for row in rows]


def get_catalog_map(conn: sqlite3.Connection) -> dict[tuple[str, str], _CatalogEntry]:
    rows = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM capability_catalog"
    ).fetchall()
    return {(row["kind"], row["id"]): _row_to_entry(row) for row in rows}


def upsert_user_capability(conn: sqlite3.Connection, kind: str, body: CapabilityAdminRequest) -> CapabilityCatalogItem:
    if not body.id.strip():
        raise HTTPException(400, "id must not be empty")
    if kind not in ("mcp_server", "skill"):
        raise HTTPException(400, f"unknown kind: {kind}")
    existing = conn.execute(
        "SELECT id, source FROM capability_catalog WHERE kind = ? AND id = ?",
        (kind, body.id),
    ).fetchone()
    if existing is not None and existing["source"] != "user":
        raise HTTPException(409, f"capability {kind}/{body.id} is built-in and cannot be modified")
    requires_ids = body.requires_ids
    if kind == "mcp_server" and requires_ids:
        raise HTTPException(400, "mcp_server capabilities cannot declare requires_ids")
    required_skill_ids = body.required_skill_ids
    if kind == "skill" and required_skill_ids:
        raise HTTPException(400, "skill capabilities cannot declare required_skill_ids")
    preferred_mcp_ids = body.preferred_mcp_ids
    if kind == "mcp_server" and preferred_mcp_ids:
        raise HTTPException(400, "mcp_server capabilities cannot declare preferred_mcp_ids")
    if kind == "mcp_server" and required_skill_ids:
        # Each id must resolve to an existing skill row. Caught at write
        # time so the UI gets a clear 400 instead of silently dropping
        # the binding at expansion. Mirrors the skill.requires_ids
        # existence check below.
        for rid in required_skill_ids:
            row = conn.execute(
                "SELECT 1 FROM capability_catalog WHERE kind = 'skill' AND id = ?",
                (rid,),
            ).fetchone()
            if row is None:
                raise HTTPException(400, f"required skill id not in catalog: {rid}")
    if kind == "skill" and preferred_mcp_ids:
        for rid in preferred_mcp_ids:
            row = conn.execute(
                "SELECT 1 FROM capability_catalog WHERE kind = 'mcp_server' AND id = ?",
                (rid,),
            ).fetchone()
            if row is None:
                raise HTTPException(400, f"preferred MCP id not in catalog: {rid}")
    if kind == "skill" and requires_ids:
        # Reject self-reference and missing targets up front so the user
        # gets a clear 400 rather than a SQL constraint error later.
        if body.id in requires_ids:
            raise HTTPException(400, "a skill cannot require itself")
        for rid in requires_ids:
            row = conn.execute(
                "SELECT 1 FROM capability_catalog WHERE kind = 'skill' AND id = ?",
                (rid,),
            ).fetchone()
            if row is None:
                raise HTTPException(400, f"requires skill id not in catalog: {rid}")
    # Cycle detection across the skill dependency graph.
    if kind == "skill" and requires_ids:
        _assert_no_skill_cycle(conn, body.id, set(requires_ids))
    now = utcnow()
    detail = body.detail
    if kind == "mcp_server" and body.transport:
        detail = body.transport
    if existing is None:
        conn.execute(
            """
            INSERT INTO capability_catalog (
                kind, id, name, description, task_types, available, detail,
                source, requires_ids, required_skill_ids, use_when, activation_hint,
                preferred_mcp_ids, probe_config, updated_at,
                source_path, transport, command, args, url, bearer_token_env, headers
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'user', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kind, body.id, body.name, body.description,
                json.dumps(body.task_types, ensure_ascii=False),
                1 if body.available else 0, detail,
                json.dumps(requires_ids, ensure_ascii=False),
                json.dumps(required_skill_ids, ensure_ascii=False),
                json.dumps(body.use_when or [], ensure_ascii=False),
                body.activation_hint,
                json.dumps(preferred_mcp_ids, ensure_ascii=False),
                json.dumps(body.probe_config or {}, ensure_ascii=False),
                now,
                body.source_path, body.transport, body.command,
                json.dumps(body.args or []),
                body.url, body.bearer_token_env,
                json.dumps(body.headers or {}),
            ),
        )
    else:
        conn.execute(
            """
            UPDATE capability_catalog SET
                name = ?, description = ?, task_types = ?, available = ?, detail = ?,
                requires_ids = ?, required_skill_ids = ?, use_when = ?, activation_hint = ?,
                preferred_mcp_ids = ?, probe_config = ?, updated_at = ?,
                source_path = ?, transport = ?, command = ?, args = ?,
                url = ?, bearer_token_env = ?, headers = ?
            WHERE kind = ? AND id = ?
            """,
            (
                body.name, body.description,
                json.dumps(body.task_types, ensure_ascii=False),
                1 if body.available else 0, detail,
                json.dumps(requires_ids, ensure_ascii=False),
                json.dumps(required_skill_ids, ensure_ascii=False),
                json.dumps(body.use_when or [], ensure_ascii=False),
                body.activation_hint,
                json.dumps(preferred_mcp_ids, ensure_ascii=False),
                json.dumps(body.probe_config or {}, ensure_ascii=False),
                now,
                body.source_path, body.transport, body.command,
                json.dumps(body.args or []),
                body.url, body.bearer_token_env,
                json.dumps(body.headers or {}),
                kind, body.id,
            ),
        )
    row = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM capability_catalog WHERE kind = ? AND id = ?",
        (kind, body.id),
    ).fetchone()
    return _row_to_entry(row).item


def delete_user_capability(conn: sqlite3.Connection, kind: str, capability_id: str) -> None:
    row = conn.execute(
        "SELECT source FROM capability_catalog WHERE kind = ? AND id = ?",
        (kind, capability_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"{kind} not found: {capability_id}")
    if row["source"] != "user":
        raise HTTPException(409, f"{kind}/{capability_id} is built-in and cannot be deleted")
    dependents = conn.execute(
        "SELECT id FROM capability_catalog WHERE kind = 'skill' AND requires_ids LIKE ?",
        (f'%"{capability_id}"%',),
    ).fetchall()
    if dependents:
        names = ", ".join(row["id"] for row in dependents)
        raise HTTPException(409, f"cannot delete: still required by {names}")
    conn.execute(
        "DELETE FROM capability_catalog WHERE kind = ? AND id = ?",
        (kind, capability_id),
    )


def register_builtin_catalog(
    conn: sqlite3.Connection, catalog: list[dict[str, Any]]
) -> list[CapabilityCatalogItem]:
    """Replace built-in rows with the dispatcher's catalog.

    Rows whose source is ``user`` are preserved: the dispatcher can't
    delete a profile an operator added from the UI.
    """
    now = utcnow()
    conn.execute(
        "DELETE FROM capability_catalog WHERE source = 'builtin'"
    )
    for item in catalog:
        kind = item.get("kind")
        cid = item.get("id")
        if not kind or not cid:
            continue
        if kind not in ("mcp_server", "skill"):
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO capability_catalog (
                kind, id, name, description, task_types, available, detail,
                source, requires_ids, required_skill_ids, use_when, activation_hint,
                preferred_mcp_ids, probe_config, updated_at,
                source_path, transport, command, args, url, bearer_token_env, headers
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'builtin', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kind, cid,
                item.get("name", cid),
                item.get("description", ""),
                json.dumps(item.get("task_types", []), ensure_ascii=False),
                1 if item.get("available", True) else 0,
                item.get("detail", ""),
                json.dumps(item.get("requires_ids", []), ensure_ascii=False),
                json.dumps(item.get("required_skill_ids", []), ensure_ascii=False),
                json.dumps(item.get("use_when", []), ensure_ascii=False),
                item.get("activation_hint", ""),
                json.dumps(item.get("preferred_mcp_ids", []), ensure_ascii=False),
                json.dumps(item.get("probe_config", {}), ensure_ascii=False),
                now,
                item.get("source_path"),
                item.get("transport"),
                item.get("command"),
                json.dumps(item.get("args", []), ensure_ascii=False),
                item.get("url"),
                item.get("bearer_token_env"),
                json.dumps(item.get("headers", {}), ensure_ascii=False),
            ),
        )
    return list_catalog(conn)


# ---------------------------------------------------------------------------
# Per-task selection expansion
# ---------------------------------------------------------------------------


def _assert_no_skill_cycle(conn: sqlite3.Connection, root_id: str, requires: Iterable[str]) -> None:
    """Reject a requires graph that would loop back to ``root_id``.

    Walk the full graph so an indirect cycle (a -> b -> a, written in
    either order) is caught the moment the second edge is added.
    """
    requires_set = {item for item in requires}
    if root_id in requires_set:
        raise HTTPException(400, f"skill requires cycle detected at {root_id}")

    def fetch_requires(node: str) -> list[str]:
        if node == root_id:
            return list(requires_set)
        row = conn.execute(
            "SELECT requires_ids FROM capability_catalog WHERE kind = 'skill' AND id = ?",
            (node,),
        ).fetchone()
        if row is None:
            return []
        try:
            return json.loads(row["requires_ids"] or "[]")
        except json.JSONDecodeError:
            return []

    visiting: set[str] = set()

    def dfs(node: str) -> None:
        if node in visiting:
            raise HTTPException(400, f"skill requires cycle detected at {node}")
        visiting.add(node)
        for child in fetch_requires(node):
            if child == root_id:
                raise HTTPException(400, f"skill requires cycle detected at {root_id}")
            if child not in visiting:
                dfs(child)
        visiting.remove(node)

    for child in list(requires_set):
        if child == root_id:
            raise HTTPException(400, f"skill requires cycle detected at {root_id}")
        dfs(child)


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
        # separated user picks from auto-required skills and do not
        # want the wire-compat auto-fill (in TaskCapabilities._dedupe
        # / before-validator) to overwrite user_skill_ids.
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


def persist_project_capabilities_per_task(
    conn: sqlite3.Connection,
    project_id: str,
    per_task: TaskCapabilitiesMap,
    now: str,
) -> TaskCapabilitiesMap:
    """Replace the per-task snapshot rows for a project.

    Caller is expected to have validated the ids via
    :func:`expand_task_capabilities` first; this function only writes
    the resulting rows. Existing rows are deleted inside an immediate
    transaction so the per-task view is always consistent for a given
    project.
    """
    conn.execute(
        "DELETE FROM project_capability_snapshots WHERE project_id = ?",
        (project_id,),
    )
    # Also wipe the legacy flat table to keep the UI banner from
    # showing stale rows for projects that have been re-saved.
    conn.execute(
        "DELETE FROM project_capabilities WHERE project_id = ?",
        (project_id,),
    )
    for task in TASK_TYPES:
        selection = per_task.get(task) or TaskCapabilities()
        for position, cid in enumerate(selection.mcp_server_ids):
            conn.execute(
                """
                INSERT INTO project_capability_snapshots (
                    project_id, task_type, kind, capability_id, source, position, created_at
                ) VALUES (?, ?, 'mcp_server', ?, 'selected', ?, ?)
                """,
                (project_id, task, cid, position, now),
            )
        for position, cid in enumerate(selection.skill_ids):
            if cid in (selection.user_skill_ids or []):
                source = "selected"
            elif cid in (selection.role_default_skill_ids or []):
                source = "role_default"
            else:
                source = "required"
            conn.execute(
                """
                INSERT INTO project_capability_snapshots (
                    project_id, task_type, kind, capability_id, source, position, created_at
                ) VALUES (?, ?, 'skill', ?, ?, ?, ?)
                """,
                (project_id, task, cid, source, position, now),
            )
    return per_task


def load_project_capabilities_per_task(
    conn: sqlite3.Connection, project_id: str
) -> TaskCapabilitiesMap:
    rows = conn.execute(
        """
        SELECT task_type, kind, capability_id, source
        FROM project_capability_snapshots
        WHERE project_id = ?
        ORDER BY task_type, kind, position
        """,
        (project_id,),
    ).fetchall()
    out: TaskCapabilitiesMap = task_capabilities_map(None)
    for row in rows:
        task = row["task_type"]
        kind = row["kind"]
        cid = row["capability_id"]
        if task not in out:
            continue
        if kind == "mcp_server":
            out[task].mcp_server_ids.append(cid)
            if row["source"] == "selected":
                out[task].user_mcp_server_ids.append(cid)
        elif kind == "skill":
            out[task].skill_ids.append(cid)
            if row["source"] == "selected":
                out[task].user_skill_ids.append(cid)
            elif row["source"] == "role_default":
                out[task].role_default_skill_ids.append(cid)
    return out


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
    if entry.transport == "stdio" or (
        (entry.transport is None or entry.transport == "")
        and (entry.source_path or entry.command)
    ):
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


def probe_capability(conn: sqlite3.Connection, kind: str, capability_id: str) -> CapabilityHealthEntry:
    row = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM capability_catalog WHERE kind = ? AND id = ?",
        (kind, capability_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"{kind} not found: {capability_id}")
    entry = _row_to_entry(row)
    if kind == "mcp_server":
        return _probe_mcp(entry)
    if kind == "skill":
        return _probe_skill(entry)
    raise HTTPException(400, f"unknown kind: {kind}")


def probe_per_task(
    conn: sqlite3.Connection,
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


def persist_probe_result(
    conn: sqlite3.Connection,
    health: dict[str, list[CapabilityHealthEntry]],
) -> None:
    """Mirror the per-capability status into the catalog row for the UI."""
    seen: set[tuple[str, str]] = set()
    for entries in health.values():
        for entry in entries:
            key = ("mcp_server" if "/" in (entry.capability_id or "") else "skill", entry.capability_id)
            if key in seen:
                continue
            seen.add(key)
            conn.execute(
                """
                UPDATE capability_catalog SET
                    last_probe_status = ?, last_probe_at = ?, last_probe_message = ?
                WHERE id = ?
                """,
                (entry.status, utcnow(), entry.message or "", entry.capability_id),
            )
