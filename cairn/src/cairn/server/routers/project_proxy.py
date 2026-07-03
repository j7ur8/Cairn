from __future__ import annotations

from fastapi import APIRouter

from cairn.server import db
from cairn.server.application.project_proxy import (
    delete_project_proxy_endpoint as delete_project_proxy_endpoint_command,
)
from cairn.server.application.project_proxy import (
    list_project_proxy_endpoints as list_project_proxy_endpoints_query,
)
from cairn.server.application.project_proxy import (
    record_project_proxy_usage as record_project_proxy_usage_command,
)
from cairn.server.application.project_proxy import (
    register_project_proxy_endpoint as register_project_proxy_endpoint_command,
)
from cairn.server.application.project_proxy import (
    resolve_project_proxy_chain as resolve_project_proxy_chain_query,
)
from cairn.server.application.project_proxy import (
    test_project_proxy_endpoint as test_project_proxy_endpoint_command,
)
from cairn.server.application.project_proxy import (
    update_project_proxy_endpoint as update_project_proxy_endpoint_command,
)
from cairn.server.schemas.project_proxy import (
    ProjectProxyChainResult,
    ProjectProxyEndpoint,
    ProjectProxyEndpointCreate,
    ProjectProxyEndpointUpdate,
    ProjectProxyTestRequest,
    ProjectProxyUsageResult,
)

router = APIRouter(tags=["project-proxy"])


@router.get("/projects/{project_id}/proxy-endpoints", response_model=list[ProjectProxyEndpoint])
def list_project_proxy_endpoints(project_id: str):
    with db.session_scope() as conn:
        return list_project_proxy_endpoints_query(conn, project_id)


@router.post("/projects/{project_id}/proxy-endpoints", response_model=ProjectProxyEndpoint, status_code=201)
def register_project_proxy_endpoint(project_id: str, body: ProjectProxyEndpointCreate):
    with db.session_scope() as conn:
        return register_project_proxy_endpoint_command(conn, project_id, body)


@router.put("/projects/{project_id}/proxy-endpoints/{endpoint_id}", response_model=ProjectProxyEndpoint)
def update_project_proxy_endpoint(project_id: str, endpoint_id: str, body: ProjectProxyEndpointUpdate):
    with db.session_scope() as conn:
        return update_project_proxy_endpoint_command(conn, project_id, endpoint_id, body)


@router.delete("/projects/{project_id}/proxy-endpoints/{endpoint_id}", status_code=204)
def delete_project_proxy_endpoint(project_id: str, endpoint_id: str):
    with db.session_scope() as conn:
        delete_project_proxy_endpoint_command(conn, project_id, endpoint_id)
    return None


@router.get("/projects/{project_id}/proxy-endpoints/{endpoint_id}/resolve-chain", response_model=ProjectProxyChainResult)
def resolve_project_proxy_chain(project_id: str, endpoint_id: str):
    with db.session_scope() as conn:
        return resolve_project_proxy_chain_query(conn, project_id, endpoint_id)


@router.post("/projects/{project_id}/proxy-endpoints/{endpoint_id}/test", response_model=ProjectProxyEndpoint)
def test_project_proxy_endpoint(project_id: str, endpoint_id: str, _body: ProjectProxyTestRequest):
    with db.session_scope() as conn:
        return test_project_proxy_endpoint_command(conn, project_id, endpoint_id)


@router.post("/projects/{project_id}/proxy-endpoints/{endpoint_id}/usage", response_model=ProjectProxyEndpoint)
def record_project_proxy_usage(project_id: str, endpoint_id: str, body: ProjectProxyUsageResult):
    with db.session_scope() as conn:
        return record_project_proxy_usage_command(conn, project_id, endpoint_id, ok=body.ok, message=body.message)
