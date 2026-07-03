from __future__ import annotations

from typing import Any

from cairn.server.repositories.project_proxy import ProjectProxyRepository
from cairn.server.schemas.project_proxy import (
    ProjectProxyChainResult,
    ProjectProxyEndpoint,
    ProjectProxyEndpointCreate,
    ProjectProxyEndpointUpdate,
)


def list_project_proxy_endpoints(conn: Any, project_id: str) -> list[ProjectProxyEndpoint]:
    return ProjectProxyRepository(conn).list(project_id)


def register_project_proxy_endpoint(
    conn: Any,
    project_id: str,
    body: ProjectProxyEndpointCreate,
) -> ProjectProxyEndpoint:
    return ProjectProxyRepository(conn).create(project_id, body)


def update_project_proxy_endpoint(
    conn: Any,
    project_id: str,
    endpoint_id: str,
    body: ProjectProxyEndpointUpdate,
) -> ProjectProxyEndpoint:
    return ProjectProxyRepository(conn).update(project_id, endpoint_id, body)


def delete_project_proxy_endpoint(conn: Any, project_id: str, endpoint_id: str) -> None:
    ProjectProxyRepository(conn).delete(project_id, endpoint_id)


def resolve_project_proxy_chain(conn: Any, project_id: str, endpoint_id: str) -> ProjectProxyChainResult:
    return ProjectProxyRepository(conn).resolve_chain(project_id, endpoint_id)


def test_project_proxy_endpoint(conn: Any, project_id: str, endpoint_id: str) -> ProjectProxyEndpoint:
    repo = ProjectProxyRepository(conn)
    endpoint = repo.get(project_id, endpoint_id)
    return repo.record_test(project_id, endpoint.id, ok=True, message="registered endpoint; active network test is tool-specific")


def record_project_proxy_usage(
    conn: Any,
    project_id: str,
    endpoint_id: str,
    *,
    ok: bool,
    message: str,
) -> ProjectProxyEndpoint:
    return ProjectProxyRepository(conn).record_usage(project_id, endpoint_id, ok=ok, message=message)
