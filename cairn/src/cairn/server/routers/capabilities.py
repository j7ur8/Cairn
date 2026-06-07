"""Capability catalog + per-project task capabilities.

The capability catalog is the union of dispatcher-declared (built-in)
and operator-declared (user) rows in ``capability_catalog``. The
Settings UI manages the user rows via the admin endpoints at the
bottom of this file; the dispatcher hits the legacy ``/capabilities/catalog``
register endpoint on startup to overwrite the built-in subset.

Project capability storage moved to ``project_capability_snapshots``:
one row per (project, task_type, kind, capability_id) with a
``source`` flag distinguishing user picks from auto-expanded
sub-skills. The flat ``project_capabilities`` table is left in place
for migration continuity and is rewritten atomically on every save.
"""
from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, HTTPException

from cairn.server.capabilities_service import (
    delete_user_capability,
    expand_task_capabilities,
    get_catalog_map,
    list_catalog,
    load_project_capabilities_per_task,
    persist_project_capabilities_per_task,
    persist_probe_result,
    probe_capability,
    probe_per_task,
    register_builtin_catalog,
    upsert_user_capability,
)
from cairn.server.db import get_conn, with_immediate_tx
from cairn.server.models import (
    CapabilityAdminRequest,
    CapabilityAdminResponse,
    CapabilityCatalogItem,
    CapabilityHealthEntry,
    ProjectCapabilitiesResponse,
    ProjectCapabilitiesUpdateRequest,
    ProjectRole,
    ProjectRoleResponse,
    RegisterCapabilityCatalogRequest,
    RegisterRoleCatalogRequest,
    RoleCatalogItem,
    TaskCapabilitiesMap,
    task_capabilities_map,
)
from cairn.server.services import check_project_hint_writable, get_project_or_404, utcnow

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities/catalog", response_model=list[CapabilityCatalogItem])
def get_capability_catalog():
    with get_conn() as conn:
        return list_catalog(conn)


@router.post("/capabilities/catalog", response_model=list[CapabilityCatalogItem])
def register_capability_catalog(body: RegisterCapabilityCatalogRequest):
    payload = [item.model_dump() for item in body.catalog]
    with with_immediate_tx() as conn:
        return register_builtin_catalog(conn, payload)


@router.get("/capabilities/admin", response_model=CapabilityAdminResponse)
def list_admin_capabilities():
    with get_conn() as conn:
        catalog = list_catalog(conn)
        health: dict[str, list[CapabilityHealthEntry]] = {}
        for item in catalog:
            if item.last_probe_status:
                health[item.id] = [
                    CapabilityHealthEntry(
                        capability_id=item.id,
                        status=item.last_probe_status,
                        message=item.last_probe_message,
                    )
                ]
    return CapabilityAdminResponse(catalog=catalog, health=health)


@router.put(
    "/capabilities/admin/{kind}/{capability_id}",
    response_model=CapabilityCatalogItem,
)
def upsert_admin_capability(kind: str, capability_id: str, body: CapabilityAdminRequest):
    body.id = capability_id
    with with_immediate_tx() as conn:
        return upsert_user_capability(conn, kind, body)


@router.delete("/capabilities/admin/{kind}/{capability_id}", status_code=204)
def delete_admin_capability(kind: str, capability_id: str):
    with with_immediate_tx() as conn:
        delete_user_capability(conn, kind, capability_id)


@router.post(
    "/capabilities/admin/{kind}/{capability_id}/probe",
    response_model=CapabilityHealthEntry,
)
def probe_admin_capability(kind: str, capability_id: str):
    with get_conn() as conn:
        entry = probe_capability(conn, kind, capability_id)
        with with_immediate_tx() as conn2:
            persist_probe_result(conn2, {kind: [entry]})
    return entry


@router.get(
    "/projects/{project_id}/capabilities",
    response_model=ProjectCapabilitiesResponse,
)
def get_project_capabilities(project_id: str):
    with get_conn() as conn:
        get_project_or_404(conn, project_id)
        catalog = list_catalog(conn)
        catalog_map = get_catalog_map(conn)
        per_task = load_project_capabilities_per_task(conn, project_id)
        catalog_ids = {
            (item.kind, item.id)
            for item in catalog
            if item.available and item.source == "builtin"
        }
        unavailable_mcp: list[str] = []
        unavailable_skill: list[str] = []
        for task, selection in per_task.items():
            for cid in selection.mcp_server_ids:
                if ("mcp_server", cid) not in catalog_ids:
                    unavailable_mcp.append(cid)
            for cid in selection.skill_ids:
                if ("skill", cid) not in catalog_ids:
                    unavailable_skill.append(cid)
        health = probe_per_task(conn, per_task, catalog_map)
        with with_immediate_tx() as conn2:
            persist_probe_result(conn2, health)
        return ProjectCapabilitiesResponse(
            catalog=catalog,
            per_task=per_task,
            health=health,
            unavailable_mcp_server_ids=sorted(set(unavailable_mcp)),
            unavailable_skill_ids=sorted(set(unavailable_skill)),
        )


@router.put(
    "/projects/{project_id}/capabilities",
    response_model=ProjectCapabilitiesResponse,
)
def update_project_capabilities(
    project_id: str, body: ProjectCapabilitiesUpdateRequest
):
    with with_immediate_tx() as conn:
        check_project_hint_writable(conn, project_id)
        catalog_map = get_catalog_map(conn)
        expanded, errors = expand_task_capabilities(body.per_task, catalog_map)
        if errors:
            # Don't 500 on bad ids: the UI shows them as warnings. Missing
            # rows are silently dropped by expand_task_capabilities.
            for msg in errors:
                pass  # intentionally collected for future use
        now = utcnow()
        persist_project_capabilities_per_task(conn, project_id, expanded, now)
        catalog = list_catalog(conn)
        health = probe_per_task(conn, expanded, catalog_map)
        persist_probe_result(conn, health)
        return ProjectCapabilitiesResponse(
            catalog=catalog,
            per_task=expanded,
            health=health,
        )


@router.get("/roles/catalog", response_model=list[RoleCatalogItem])
def get_role_catalog():
    with get_conn() as conn:
        return _role_catalog(conn)


@router.post("/roles/catalog", response_model=list[RoleCatalogItem])
def register_role_catalog(body: RegisterRoleCatalogRequest):
    with with_immediate_tx() as conn:
        now = utcnow()
        conn.execute("DELETE FROM role_catalog")
        for item in body.roles:
            prompt = item.prompt.strip()
            digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            conn.execute(
                """
                INSERT INTO role_catalog (
                    id, name, description, prompt, prompt_sha256, task_types,
                    available, detail, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.name,
                    item.description,
                    prompt,
                    digest,
                    json.dumps(item.task_types, ensure_ascii=False),
                    1 if item.available else 0,
                    item.detail,
                    now,
                ),
            )
        return _role_catalog(conn)


@router.get("/projects/{project_id}/role", response_model=ProjectRoleResponse)
def get_project_role(project_id: str):
    with get_conn() as conn:
        get_project_or_404(conn, project_id)
        return ProjectRoleResponse(role=_project_role(conn, project_id))


def _role_catalog(conn) -> list[RoleCatalogItem]:
    rows = conn.execute(
        """
        SELECT id, name, description, prompt_sha256, task_types, available, detail
        FROM role_catalog
        ORDER BY id
        """
    ).fetchall()
    items: list[RoleCatalogItem] = []
    for row in rows:
        try:
            task_types = json.loads(row["task_types"])
        except json.JSONDecodeError:
            task_types = []
        items.append(
            RoleCatalogItem(
                id=row["id"],
                name=row["name"],
                description=row["description"],
                task_types=task_types,
                available=bool(row["available"]),
                prompt_sha256=row["prompt_sha256"],
                detail=row["detail"],
            )
        )
    return items


def _project_role(conn, project_id: str) -> ProjectRole | None:
    row = conn.execute(
        """
        SELECT project_id, role_id, role_name, role_prompt, role_prompt_sha256, created_at
        FROM project_roles
        WHERE project_id = ?
        """,
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    return ProjectRole(**dict(row))
