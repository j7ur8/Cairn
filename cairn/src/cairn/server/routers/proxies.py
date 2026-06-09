"""CRUD endpoints for the YAML-backed system-wide proxy pool."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cairn.server.models import (
    ProxyConfig,
    ProxyCreate,
    ProxySummary,
    ProxyUpdate,
)
from cairn.server.yaml_config import (
    create_yaml_proxy,
    delete_yaml_proxy,
    get_yaml_proxy,
    list_yaml_proxies,
    update_yaml_proxy,
)
from cairn.server.db import get_conn

router = APIRouter(tags=["proxies"])


@router.get("/proxies", response_model=list[ProxySummary])
def list_proxies():
    return list_yaml_proxies()


@router.post("/proxies", response_model=ProxyConfig, status_code=201)
def create_proxy(body: ProxyCreate):
    return create_yaml_proxy(body)


@router.get("/proxies/{proxy_id}", response_model=ProxyConfig)
def get_proxy(proxy_id: str):
    return get_yaml_proxy(proxy_id)


@router.put("/proxies/{proxy_id}", response_model=ProxyConfig)
def update_proxy(proxy_id: str, body: ProxyUpdate):
    return update_yaml_proxy(proxy_id, body)


@router.delete("/proxies/{proxy_id}", status_code=204)
def delete_proxy(proxy_id: str):
    try:
        delete_yaml_proxy(proxy_id)
    except HTTPException:
        raise
    with get_conn() as conn:
        conn.execute("UPDATE projects SET proxy_id = NULL WHERE proxy_id = ?", (proxy_id,))
        conn.commit()
    return None
