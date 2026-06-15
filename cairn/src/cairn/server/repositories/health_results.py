from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from cairn.server.repositories import sql


def _utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id() -> str:
    return f"hcr_{uuid.uuid4().hex[:12]}"


class HealthCheckResultRepository:
    """CRUD for the ``health_check_results`` table."""

    def __init__(self, conn: Any):
        self.conn = conn

    def insert(
        self,
        *,
        profile_id: str,
        ok: bool,
        latency_ms: int | None = None,
        http_status: int | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        check_type: str = "manual",
    ) -> str:
        row_id = _new_id()
        sql.execute(
            self.conn,
            """INSERT INTO health_check_results
               (id, profile_id, checked_at, ok, latency_ms, http_status,
                error_type, error_message, check_type)
               VALUES
               (:id, :profile_id, :checked_at, :ok, :latency_ms, :http_status,
                :error_type, :error_message, :check_type)""",
            {
                "id": row_id,
                "profile_id": profile_id,
                "checked_at": _utcnow(),
                "ok": ok,
                "latency_ms": latency_ms,
                "http_status": http_status,
                "error_type": error_type,
                "error_message": error_message,
                "check_type": check_type,
            },
        )
        return row_id

    def latest_for_profile(self, profile_id: str) -> dict | None:
        return sql.fetchone(
            self.conn,
            """SELECT * FROM health_check_results
               WHERE profile_id = :profile_id
               ORDER BY checked_at DESC
               LIMIT 1""",
            {"profile_id": profile_id},
        )

    def all_latest(self) -> list[dict]:
        """One row per profile_id: the most recent health result for each."""
        return sql.fetchall(
            self.conn,
            """SELECT * FROM health_check_results
               WHERE id IN (
                 SELECT id FROM (
                   SELECT id, ROW_NUMBER() OVER (
                     PARTITION BY profile_id ORDER BY checked_at DESC
                   ) rn FROM health_check_results
                 ) ranked WHERE rn = 1
               )""",
        )
