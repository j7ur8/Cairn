from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from cairn.server.config.files import load_resources_data, save_resources_data, utcnow
from cairn.shared.config import ServerResourceConfig, ServerResourcePublic


class ServerYamlRepository:
    def list(self) -> list[ServerResourceConfig]:
        data = load_resources_data()
        return [ServerResourceConfig.model_validate(item) for item in self._servers(data)]

    def get(self, server_id: str) -> ServerResourceConfig:
        for server in self.list():
            if server.id == server_id:
                return server
        raise HTTPException(404, f"server not found: {server_id}")

    def create(self, payload: dict[str, Any]) -> ServerResourceConfig:
        data = load_resources_data()
        entries = self._servers(data)
        if any(isinstance(item, dict) and item.get("id") == payload.get("id") for item in entries):
            raise HTTPException(409, f"server already exists: {payload.get('id')}")
        payload.setdefault("last_test_ok", None)
        payload.setdefault("last_test_at", None)
        payload.setdefault("last_test_message", "")
        server = ServerResourceConfig.model_validate(payload)
        entries.append(server.model_dump(exclude_none=True))
        save_resources_data(data)
        return server

    def update(self, server_id: str, payload: dict[str, Any]) -> tuple[ServerResourceConfig, str | None]:
        data = load_resources_data()
        entries = self._servers(data)
        for idx, item in enumerate(entries):
            if not isinstance(item, dict) or item.get("id") != server_id:
                continue
            old_cert_path = item.get("cert_path")
            payload["id"] = server_id
            server = ServerResourceConfig.model_validate(payload)
            entries[idx] = server.model_dump(exclude_none=True)
            save_resources_data(data)
            return server, old_cert_path if isinstance(old_cert_path, str) else None
        raise HTTPException(404, f"server not found: {server_id}")

    def delete(self, server_id: str) -> None:
        data = load_resources_data()
        entries = self._servers(data)
        for idx, item in enumerate(entries):
            if isinstance(item, dict) and item.get("id") == server_id:
                entries.pop(idx)
                save_resources_data(data)
                return
        raise HTTPException(404, f"server not found: {server_id}")

    def record_test_result(self, server_id: str, ok: bool, message: str) -> None:
        data = load_resources_data()
        entries = self._servers(data)
        for item in entries:
            if isinstance(item, dict) and item.get("id") == server_id:
                item["last_test_ok"] = ok
                item["last_test_at"] = utcnow()
                item["last_test_message"] = message[:1000]
                save_resources_data(data, reload_dispatcher=False)
                return

    def raw_payload_for_update(self, server_id: str) -> dict[str, Any]:
        data = load_resources_data()
        for item in self._servers(data):
            if isinstance(item, dict) and item.get("id") == server_id:
                return dict(item)
        raise HTTPException(404, f"server not found: {server_id}")

    def _servers(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        entries = data.setdefault("servers", [])
        if not isinstance(entries, list):
            raise HTTPException(500, "config.resources.yaml servers must be a list")
        return entries


def public_server(server: ServerResourceConfig) -> ServerResourcePublic:
    return ServerResourcePublic(
        id=server.id,
        name=server.name,
        enabled=server.enabled,
        host=server.host,
        port=server.port,
        username=server.username,
        auth_order=list(server.auth_order),
        has_password=bool(server.password),
        has_private_key=bool(server.private_key),
        cert_path=server.cert_path,
        description=server.description,
        last_test_ok=server.last_test_ok,
        last_test_at=server.last_test_at,
        last_test_message=server.last_test_message,
    )
