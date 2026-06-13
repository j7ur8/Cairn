"""Capability catalog and project execution snapshots."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from cairn.server import db
from cairn.server.application.capabilities import (
    get_project_capabilities as get_project_capabilities_query,
)
from cairn.server.application.capabilities import (
    get_project_role as get_project_role_query,
)
from cairn.server.capability_health import probe_capability
from cairn.server.config.capabilities import (
    delete_yaml_capability,
    list_yaml_capabilities,
    upsert_yaml_capability,
)
from cairn.server.config.roles import list_yaml_roles
from cairn.server.models_pkg import (
    CapabilityAdminRequest,
    CapabilityAdminResponse,
    CapabilityCatalogItem,
    CapabilityHealthEntry,
    ProjectCapabilitiesResponse,
    ProjectCapabilitiesUpdateRequest,
    ProjectRoleResponse,
    RoleCatalogItem,
)
from cairn.server.security.deps import current_active_superuser

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities/catalog", response_model=list[CapabilityCatalogItem])
def get_capability_catalog():
    return list_yaml_capabilities()


@router.get("/capabilities/admin", response_model=CapabilityAdminResponse)
def list_admin_capabilities(_superuser=Depends(current_active_superuser)):
    catalog = list_yaml_capabilities()
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
def upsert_admin_capability(
    kind: str,
    capability_id: str,
    body: CapabilityAdminRequest,
    _superuser=Depends(current_active_superuser),
):
    body.id = capability_id
    return upsert_yaml_capability(kind, capability_id, body)


@router.delete("/capabilities/admin/{kind}/{capability_id}", status_code=204)
def delete_admin_capability(kind: str, capability_id: str, _superuser=Depends(current_active_superuser)):
    delete_yaml_capability(kind, capability_id)


@router.post(
    "/capabilities/admin/{kind}/{capability_id}/probe",
    response_model=CapabilityHealthEntry,
)
def probe_admin_capability(kind: str, capability_id: str, _superuser=Depends(current_active_superuser)):
    return probe_capability(None, kind, capability_id)


@router.get(
    "/projects/{project_id}/capabilities",
    response_model=ProjectCapabilitiesResponse,
)
def get_project_capabilities(project_id: str):
    with db.session_scope() as conn:
        return get_project_capabilities_query(conn, project_id)


@router.put(
    "/projects/{project_id}/capabilities",
    response_model=ProjectCapabilitiesResponse,
)
def update_project_capabilities(
    project_id: str, body: ProjectCapabilitiesUpdateRequest
):
    raise HTTPException(410, "project capabilities are immutable execution snapshots; create or replay a project")


@router.get("/roles/catalog", response_model=list[RoleCatalogItem])
def get_role_catalog():
    return list_yaml_roles()


@router.get("/projects/{project_id}/role", response_model=ProjectRoleResponse)
def get_project_role(project_id: str):
    with db.session_scope() as conn:
        return get_project_role_query(conn, project_id)
