"""CRUD endpoints for the YAML-backed system-wide proxy pool."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from cairn.server import db
from cairn.server.application.proxies import detach_proxy_from_projects
from cairn.server.config.proxies import (
    create_yaml_proxy,
    delete_yaml_proxy,
    get_yaml_proxy,
    list_yaml_proxies,
    update_yaml_proxy,
)
from cairn.server.models_pkg.proxies import ProxyCreate, ProxyUpdate
from cairn.server.security.deps import current_active_superuser
from cairn.shared.contracts import ProxyConfig, ProxySummary

router = APIRouter(tags=["proxies"])


@router.get("/proxies", response_model=list[ProxySummary])
def list_proxies():
    return list_yaml_proxies()


@router.post("/proxies", response_model=ProxyConfig, status_code=201)
def create_proxy(body: ProxyCreate, _superuser=Depends(current_active_superuser)):
    return create_yaml_proxy(body)


@router.get("/proxies/{proxy_id}", response_model=ProxyConfig)
def get_proxy(proxy_id: str, _superuser=Depends(current_active_superuser)):
    return get_yaml_proxy(proxy_id)


@router.put("/proxies/{proxy_id}", response_model=ProxyConfig)
def update_proxy(proxy_id: str, body: ProxyUpdate, _superuser=Depends(current_active_superuser)):
    return update_yaml_proxy(proxy_id, body)


@router.delete("/proxies/{proxy_id}", status_code=204)
def delete_proxy(proxy_id: str, _superuser=Depends(current_active_superuser)):
    delete_yaml_proxy(proxy_id)
    with db.session_scope() as conn:
        detach_proxy_from_projects(conn, proxy_id)
    return None
