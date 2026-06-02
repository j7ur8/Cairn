from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter

from cairn.server.db import get_conn
from cairn.server.models import (
    CapabilityCatalogItem,
    CapabilitySelection,
    ProjectCapabilitiesResponse,
    ProjectRole,
    ProjectRoleResponse,
    RegisterCapabilityCatalogRequest,
    RegisterRoleCatalogRequest,
    RoleCatalogItem,
)
from cairn.server.services import check_project_hint_writable, get_project_or_404, utcnow

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities/catalog", response_model=list[CapabilityCatalogItem])
def get_capability_catalog():
    with get_conn() as conn:
        return _catalog(conn)


@router.get("/projects/{project_id}/capabilities", response_model=ProjectCapabilitiesResponse)
def get_project_capabilities(project_id: str):
    with get_conn() as conn:
        get_project_or_404(conn, project_id)
        catalog = _catalog(conn)
        selection = _selection(conn, project_id)
        catalog_ids = {(item.kind, item.id) for item in catalog if item.available}
        unavailable_mcp = [
            capability_id
            for capability_id in selection.mcp_server_ids
            if ("mcp_server", capability_id) not in catalog_ids
        ]
        unavailable_skills = [
            capability_id
            for capability_id in selection.skill_ids
            if ("skill", capability_id) not in catalog_ids
        ]
        return ProjectCapabilitiesResponse(
            catalog=catalog,
            selection=selection,
            unavailable_mcp_server_ids=unavailable_mcp,
            unavailable_skill_ids=unavailable_skills,
        )


@router.put("/projects/{project_id}/capabilities", response_model=ProjectCapabilitiesResponse)
def update_project_capabilities(project_id: str, body: CapabilitySelection):
    with get_conn() as conn:
        check_project_hint_writable(conn, project_id)
        now = utcnow()
        conn.execute("DELETE FROM project_capabilities WHERE project_id = ?", (project_id,))
        for capability_id in body.mcp_server_ids:
            conn.execute(
                """
                INSERT INTO project_capabilities (project_id, kind, capability_id, created_at)
                VALUES (?, 'mcp_server', ?, ?)
                """,
                (project_id, capability_id, now),
            )
        for capability_id in body.skill_ids:
            conn.execute(
                """
                INSERT INTO project_capabilities (project_id, kind, capability_id, created_at)
                VALUES (?, 'skill', ?, ?)
                """,
                (project_id, capability_id, now),
            )
        catalog = _catalog(conn)
        return ProjectCapabilitiesResponse(
            catalog=catalog,
            selection=_selection(conn, project_id),
            unavailable_mcp_server_ids=_unavailable_ids(catalog, body.mcp_server_ids, "mcp_server"),
            unavailable_skill_ids=_unavailable_ids(catalog, body.skill_ids, "skill"),
        )


@router.post("/capabilities/catalog", response_model=list[CapabilityCatalogItem])
def register_capability_catalog(body: RegisterCapabilityCatalogRequest):
    with get_conn() as conn:
        now = utcnow()
        conn.execute("DELETE FROM capability_catalog")
        for item in body.catalog:
            conn.execute(
                """
                INSERT INTO capability_catalog (
                    kind, id, name, description, task_types, available, detail, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.kind,
                    item.id,
                    item.name,
                    item.description,
                    json.dumps(item.task_types, ensure_ascii=False),
                    1 if item.available else 0,
                    item.detail,
                    now,
                ),
            )
        return _catalog(conn)


@router.get("/roles/catalog", response_model=list[RoleCatalogItem])
def get_role_catalog():
    with get_conn() as conn:
        return _role_catalog(conn)


@router.post("/roles/catalog", response_model=list[RoleCatalogItem])
def register_role_catalog(body: RegisterRoleCatalogRequest):
    with get_conn() as conn:
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


def _catalog(conn) -> list[CapabilityCatalogItem]:
    rows = conn.execute(
        """
        SELECT kind, id, name, description, task_types, available, detail
        FROM capability_catalog
        ORDER BY kind, id
        """
    ).fetchall()
    items: list[CapabilityCatalogItem] = []
    for row in rows:
        try:
            task_types = json.loads(row["task_types"])
        except json.JSONDecodeError:
            task_types = []
        items.append(
            CapabilityCatalogItem(
                kind=row["kind"],
                id=row["id"],
                name=row["name"],
                description=row["description"],
                task_types=task_types,
                available=bool(row["available"]),
                detail=row["detail"],
            )
        )
    return items


def _selection(conn, project_id: str) -> CapabilitySelection:
    rows = conn.execute(
        """
        SELECT kind, capability_id
        FROM project_capabilities
        WHERE project_id = ?
        ORDER BY kind, capability_id
        """,
        (project_id,),
    ).fetchall()
    mcp_server_ids = [row["capability_id"] for row in rows if row["kind"] == "mcp_server"]
    skill_ids = [row["capability_id"] for row in rows if row["kind"] == "skill"]
    return CapabilitySelection(mcp_server_ids=mcp_server_ids, skill_ids=skill_ids)


def _unavailable_ids(catalog: list[CapabilityCatalogItem], ids: list[str], kind: str) -> list[str]:
    available = {item.id for item in catalog if item.kind == kind and item.available}
    return [capability_id for capability_id in ids if capability_id not in available]


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
