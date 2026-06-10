"""Capability catalog and project execution snapshots."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cairn.server import db
from cairn.server.capabilities_service import (
    probe_capability,
    project_capability_tasks,
    unavailable_capabilities,
)
from cairn.server.execution_config_service import (
    execution_capabilities,
    load_worker_execution_configs,
)
from cairn.server.models_pkg.capabilities import (
    CapabilityAdminRequest,
    CapabilityAdminResponse,
    CapabilityCatalogItem,
    CapabilityHealthEntry,
    ProjectCapabilitiesResponse,
    ProjectCapabilitiesUpdateRequest,
    ProjectRole,
    ProjectRoleResponse,
    RoleCatalogItem,
)
from cairn.server.services import get_project_or_404
from cairn.server.config.capabilities import (
    delete_yaml_capability,
    list_yaml_capabilities,
    upsert_yaml_capability,
)
from cairn.server.config.roles import list_yaml_roles
from cairn.shared.task_types import builtin_task_type_names

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities/catalog", response_model=list[CapabilityCatalogItem])
def get_capability_catalog():
    return list_yaml_capabilities()


@router.get("/capabilities/admin", response_model=CapabilityAdminResponse)
def list_admin_capabilities():
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
def upsert_admin_capability(kind: str, capability_id: str, body: CapabilityAdminRequest):
    body.id = capability_id
    return upsert_yaml_capability(kind, capability_id, body)


@router.delete("/capabilities/admin/{kind}/{capability_id}", status_code=204)
def delete_admin_capability(kind: str, capability_id: str):
    delete_yaml_capability(kind, capability_id)


@router.post(
    "/capabilities/admin/{kind}/{capability_id}/probe",
    response_model=CapabilityHealthEntry,
)
def probe_admin_capability(kind: str, capability_id: str):
    return probe_capability(None, kind, capability_id)


@router.get(
    "/projects/{project_id}/capabilities",
    response_model=ProjectCapabilitiesResponse,
)
def get_project_capabilities(project_id: str):
    with db.session_scope() as conn:
        get_project_or_404(conn, project_id)
        configs = load_worker_execution_configs(conn, project_id)
        catalog = list_yaml_capabilities()
        per_task = execution_capabilities(configs)
        health = {
            task: [
                CapabilityHealthEntry.model_validate(entry)
                for entry in ((configs.get(task) or {}).get("health", {}).get(task) or [])
            ]
            for task in builtin_task_type_names()
        }
        return ProjectCapabilitiesResponse(
            catalog=catalog,
            tasks=project_capability_tasks(per_task),
            health=health,
            unavailable=unavailable_capabilities(catalog, per_task),
        )


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
        get_project_or_404(conn, project_id)
        configs = load_worker_execution_configs(conn, project_id)
    role = None
    for task in builtin_task_type_names():
        raw = (configs.get(task) or {}).get("role")
        if not isinstance(raw, dict):
            continue
        role = ProjectRole(
            project_id=project_id,
            role_id=str(raw.get("id") or ""),
            role_name=str(raw.get("name") or ""),
            role_prompt=str(raw.get("prompt") or ""),
            role_prompt_sha256=str(raw.get("prompt_sha256") or ""),
            created_at="",
        )
        break
    return ProjectRoleResponse(role=role)
