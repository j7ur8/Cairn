from __future__ import annotations

import uuid
from typing import Any

from cairn.server.domain.errors import BadRequestError, NotFoundError
from cairn.server.domain.time import utcnow
from cairn.server.repositories import sql
from cairn.server.schemas.project_proxy import (
    ProjectProxyChainResult,
    ProjectProxyEndpoint,
    ProjectProxyEndpointCreate,
    ProjectProxyEndpointUpdate,
)


class ProjectProxyRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def list(self, project_id: str) -> list[ProjectProxyEndpoint]:
        rows = sql.fetchall(
            self.conn,
            "SELECT * FROM project_proxy_endpoints WHERE project_id = :project_id ORDER BY created_at, id",
            {"project_id": project_id},
        )
        return [_row_to_endpoint(row) for row in rows]

    def get(self, project_id: str, endpoint_id: str) -> ProjectProxyEndpoint:
        row = sql.fetchone(
            self.conn,
            """
            SELECT * FROM project_proxy_endpoints
            WHERE project_id = :project_id AND id = :id
            """,
            {"project_id": project_id, "id": endpoint_id},
        )
        if row is None:
            raise NotFoundError(f"project proxy endpoint not found: {endpoint_id}")
        return _row_to_endpoint(row)

    def create(self, project_id: str, body: ProjectProxyEndpointCreate) -> ProjectProxyEndpoint:
        endpoint_id = body.id or f"px_{uuid.uuid4().hex[:12]}"
        if body.prerequisite_proxy_id == endpoint_id:
            raise BadRequestError("prerequisite_proxy_id cannot reference itself")
        now = utcnow()
        payload = body.model_dump()
        _normalize_auth_payload(payload)
        payload["id"] = endpoint_id
        payload["project_id"] = project_id
        payload["created_at"] = now
        payload["updated_at"] = now
        self._validate_prerequisite(project_id, payload.get("prerequisite_proxy_id"))
        sql.execute(
            self.conn,
            """
            INSERT INTO project_proxy_endpoints (
                id, project_id, name, protocol, host, port, auth_type, username, password,
                source, lifecycle, description, scope, prerequisite_proxy_id, reachable_from,
                usage_mode, health_status, last_test_ok, last_test_at, last_test_message,
                last_used_at, last_usage_ok, last_usage_message, run_id, task_id, created_at, updated_at
            ) VALUES (
                :id, :project_id, :name, :protocol, :host, :port, :auth_type, :username, :password,
                :source, :lifecycle, :description, :scope, :prerequisite_proxy_id, :reachable_from,
                :usage_mode, 'unknown', NULL, NULL, '', NULL, NULL, '', :run_id, :task_id, :created_at, :updated_at
            )
            """,
            payload,
        )
        self._reject_cycle(project_id, endpoint_id)
        return self.get(project_id, endpoint_id)

    def update(self, project_id: str, endpoint_id: str, body: ProjectProxyEndpointUpdate) -> ProjectProxyEndpoint:
        current = self._get_row(project_id, endpoint_id)
        payload = dict(current)
        changes = body.model_dump(exclude_unset=True)
        for key, value in changes.items():
            if key == "password" and value is None and payload.get("auth_type") == "password":
                continue
            payload[key] = value
        _normalize_auth_payload(payload)
        if payload.get("prerequisite_proxy_id") == endpoint_id:
            raise BadRequestError("prerequisite_proxy_id cannot reference itself")
        self._validate_prerequisite(project_id, payload.get("prerequisite_proxy_id"))
        if self._would_create_cycle(project_id, endpoint_id, payload.get("prerequisite_proxy_id")):
            raise BadRequestError("proxy prerequisite cycle detected")
        payload["updated_at"] = utcnow()
        sql.execute(
            self.conn,
            """
            UPDATE project_proxy_endpoints
            SET name = :name,
                protocol = :protocol,
                host = :host,
                port = :port,
                auth_type = :auth_type,
                username = :username,
                password = :password,
                source = :source,
                lifecycle = :lifecycle,
                description = :description,
                scope = :scope,
                prerequisite_proxy_id = :prerequisite_proxy_id,
                reachable_from = :reachable_from,
                usage_mode = :usage_mode,
                run_id = :run_id,
                task_id = :task_id,
                updated_at = :updated_at
            WHERE project_id = :project_id AND id = :id
            """,
            payload,
        )
        self._reject_cycle(project_id, endpoint_id)
        return self.get(project_id, endpoint_id)

    def delete(self, project_id: str, endpoint_id: str) -> None:
        sql.execute(
            self.conn,
            """
            UPDATE project_proxy_endpoints
            SET prerequisite_proxy_id = NULL
            WHERE project_id = :project_id AND prerequisite_proxy_id = :id
            """,
            {"project_id": project_id, "id": endpoint_id},
        )
        cursor = sql.execute(
            self.conn,
            "DELETE FROM project_proxy_endpoints WHERE project_id = :project_id AND id = :id",
            {"project_id": project_id, "id": endpoint_id},
        )
        if cursor.rowcount == 0:
            raise NotFoundError(f"project proxy endpoint not found: {endpoint_id}")

    def resolve_chain(self, project_id: str, endpoint_id: str) -> ProjectProxyChainResult:
        by_id = {item.id: item for item in self.list(project_id)}
        if endpoint_id not in by_id:
            return ProjectProxyChainResult(ok=False, proxy_id=endpoint_id, reason="proxy endpoint not found")
        chain: list[ProjectProxyEndpoint] = []
        visiting: set[str] = set()
        current_id: str | None = endpoint_id
        while current_id:
            if current_id in visiting:
                return ProjectProxyChainResult(ok=False, proxy_id=endpoint_id, reason="proxy prerequisite cycle detected")
            visiting.add(current_id)
            current = by_id.get(current_id)
            if current is None:
                return ProjectProxyChainResult(ok=False, proxy_id=endpoint_id, reason=f"missing prerequisite proxy: {current_id}")
            chain.append(current)
            current_id = current.prerequisite_proxy_id
        chain.reverse()
        return ProjectProxyChainResult(ok=True, proxy_id=endpoint_id, chain=chain)

    def record_test(self, project_id: str, endpoint_id: str, *, ok: bool, message: str) -> ProjectProxyEndpoint:
        now = utcnow()
        sql.execute(
            self.conn,
            """
            UPDATE project_proxy_endpoints
            SET health_status = :health_status,
                last_test_ok = :ok,
                last_test_at = :now,
                last_test_message = :message,
                updated_at = :now
            WHERE project_id = :project_id AND id = :id
            """,
            {
                "project_id": project_id,
                "id": endpoint_id,
                "health_status": "ok" if ok else "error",
                "ok": ok,
                "now": now,
                "message": message[:1000],
            },
        )
        return self.get(project_id, endpoint_id)

    def record_usage(self, project_id: str, endpoint_id: str, *, ok: bool, message: str) -> ProjectProxyEndpoint:
        now = utcnow()
        sql.execute(
            self.conn,
            """
            UPDATE project_proxy_endpoints
            SET last_used_at = :now,
                last_usage_ok = :ok,
                last_usage_message = :message,
                updated_at = :now
            WHERE project_id = :project_id AND id = :id
            """,
            {"project_id": project_id, "id": endpoint_id, "now": now, "ok": ok, "message": message[:1000]},
        )
        return self.get(project_id, endpoint_id)

    def _validate_prerequisite(self, project_id: str, prerequisite_proxy_id: str | None) -> None:
        if prerequisite_proxy_id is None:
            return
        self.get(project_id, prerequisite_proxy_id)

    def _reject_cycle(self, project_id: str, endpoint_id: str) -> None:
        result = self.resolve_chain(project_id, endpoint_id)
        if not result.ok and "cycle" in result.reason:
            raise BadRequestError(result.reason)

    def _would_create_cycle(self, project_id: str, endpoint_id: str, prerequisite_proxy_id: str | None) -> bool:
        if prerequisite_proxy_id is None:
            return False
        by_id = {item.id: item for item in self.list(project_id)}
        current_id = prerequisite_proxy_id
        seen: set[str] = set()
        while current_id:
            if current_id == endpoint_id:
                return True
            if current_id in seen:
                return True
            seen.add(current_id)
            current = by_id.get(current_id)
            if current is None:
                return False
            current_id = current.prerequisite_proxy_id
        return False

    def _get_row(self, project_id: str, endpoint_id: str) -> Any:
        row = sql.fetchone(
            self.conn,
            """
            SELECT * FROM project_proxy_endpoints
            WHERE project_id = :project_id AND id = :id
            """,
            {"project_id": project_id, "id": endpoint_id},
        )
        if row is None:
            raise NotFoundError(f"project proxy endpoint not found: {endpoint_id}")
        return row


def _normalize_auth_payload(payload: dict[str, Any]) -> None:
    if payload.get("auth_type") == "none":
        payload["username"] = None
        payload["password"] = None


def _row_to_endpoint(row: Any) -> ProjectProxyEndpoint:
    has_auth = row["auth_type"] == "password" and bool(row["username"] or row["password"])
    return ProjectProxyEndpoint(
        id=row["id"],
        project_id=row["project_id"],
        name=row["name"],
        protocol=row["protocol"],
        host=row["host"],
        port=row["port"],
        auth_type=row["auth_type"],
        username=row["username"],
        password=None,
        has_auth=has_auth,
        source=row["source"] or "",
        lifecycle=row["lifecycle"],
        description=row["description"] or "",
        scope=row["scope"] or "",
        prerequisite_proxy_id=row["prerequisite_proxy_id"],
        reachable_from=row["reachable_from"] or "worker",
        usage_mode=row["usage_mode"] or "tool_native_proxy",
        health_status=row["health_status"] or "unknown",
        last_test_ok=row["last_test_ok"],
        last_test_at=row["last_test_at"],
        last_test_message=row["last_test_message"] or "",
        last_used_at=row["last_used_at"],
        last_usage_ok=row["last_usage_ok"],
        last_usage_message=row["last_usage_message"] or "",
        run_id=row["run_id"],
        task_id=row["task_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
