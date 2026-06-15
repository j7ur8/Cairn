from __future__ import annotations

from typing import Any

from cairn.server.config.files import load_dispatch_data, save_dispatch_data, utcnow
from cairn.server.domain.errors import DomainError, NotFoundError
from cairn.server.models_pkg.proxies import ProxyCreate, ProxyUpdate
from cairn.shared.contracts import ProxyConfig, ProxySummary


def list_yaml_proxies() -> list[ProxySummary]:
    data = load_dispatch_data()
    proxies = [_proxy_to_config(item) for item in _proxies(data)]
    proxies.sort(key=lambda item: (item.created_at, item.id), reverse=True)
    return [_proxy_summary(item) for item in proxies]


def get_yaml_proxy(proxy_id: str) -> ProxyConfig:
    data = load_dispatch_data()
    for item in _proxies(data):
        if item.get("id") == proxy_id:
            return _proxy_to_config(item)
    raise NotFoundError(f"proxy not found: {proxy_id}")


def create_yaml_proxy(body: ProxyCreate) -> ProxyConfig:
    data = load_dispatch_data()
    proxies = _proxies(data)
    now = utcnow()
    proxy_id = _new_proxy_id(proxies)
    entry = {
        "id": proxy_id,
        "name": body.name,
        "type": body.type,
        "host": body.host,
        "port": body.port,
        "username": body.username,
        "password": body.password,
        "created_at": now,
        "updated_at": now,
    }
    proxies.append(entry)
    save_dispatch_data(data)
    return _proxy_to_config(entry)


def update_yaml_proxy(proxy_id: str, body: ProxyUpdate) -> ProxyConfig:
    data = load_dispatch_data()
    proxies = _proxies(data)
    for item in proxies:
        if item.get("id") != proxy_id:
            continue
        for key, value in body.model_dump(exclude_unset=True).items():
            item[key] = value
        item["updated_at"] = utcnow()
        save_dispatch_data(data)
        return _proxy_to_config(item)
    raise NotFoundError(f"proxy not found: {proxy_id}")


def delete_yaml_proxy(proxy_id: str) -> None:
    data = load_dispatch_data()
    proxies = _proxies(data)
    for idx, item in enumerate(proxies):
        if item.get("id") == proxy_id:
            proxies.pop(idx)
            save_dispatch_data(data)
            return
    raise NotFoundError(f"proxy not found: {proxy_id}")


def _proxies(data: dict[str, Any]) -> list[dict[str, Any]]:
    worker_pool = data.setdefault("worker_pool", {})
    if not isinstance(worker_pool, dict):
        raise DomainError("config.yaml worker_pool must be a mapping", status_code=500)
    proxies = worker_pool.setdefault("proxies", [])
    if not isinstance(proxies, list):
        raise DomainError("config.yaml worker_pool.proxies must be a list", status_code=500)
    return proxies


def _new_proxy_id(proxies: list[dict[str, Any]]) -> str:
    used = {str(item.get("id") or "") for item in proxies}
    index = 1
    while True:
        candidate = f"proxy_{index:03d}"
        if candidate not in used:
            return candidate
        index += 1


def _proxy_to_config(item: dict[str, Any]) -> ProxyConfig:
    created = str(item.get("created_at") or utcnow())
    updated = str(item.get("updated_at") or created)
    return ProxyConfig(
        id=str(item.get("id") or ""),
        name=str(item.get("name") or ""),
        type=item.get("type") or "socks5",
        host=str(item.get("host") or ""),
        port=int(item.get("port") or 1),
        has_auth=bool(item.get("username") or item.get("password")),
        username=item.get("username"),
        password=item.get("password"),
        created_at=created,
        updated_at=updated,
    )


def _proxy_summary(item: ProxyConfig) -> ProxySummary:
    return ProxySummary(
        id=item.id,
        name=item.name,
        type=item.type,
        host=item.host,
        port=item.port,
        has_auth=item.has_auth,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
