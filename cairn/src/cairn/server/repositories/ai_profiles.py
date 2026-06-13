from __future__ import annotations

from typing import Any

from cairn.server.repositories import sql


class AiProfileCheckRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def latest_active_for_profile(self, profile_id: str) -> Any | None:
        return sql.fetchone(
            self.conn,
            """
            SELECT *
            FROM ai_profile_check_requests
            WHERE profile_id = :profile_id
              AND status IN ('pending', 'running')
            ORDER BY requested_at DESC
            LIMIT 1
            """,
            {"profile_id": profile_id},
        )

    def insert_pending(
        self,
        *,
        request_id: str,
        profile_id: str,
        requested_at: str,
        requested_by: str,
    ) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO ai_profile_check_requests (
                id, profile_id, status, requested_at, requested_by
            ) VALUES (:id, :profile_id, 'pending', :requested_at, :requested_by)
            """,
            {
                "id": request_id,
                "profile_id": profile_id,
                "requested_at": requested_at,
                "requested_by": requested_by,
            },
        )

    def claim_next(self, *, started_at: str) -> Any | None:
        return sql.execute(
            self.conn,
            """
            UPDATE ai_profile_check_requests
            SET status = 'running',
                started_at = :started_at,
                error_message = ''
            WHERE id = (
                SELECT id
                FROM ai_profile_check_requests
                WHERE status = 'pending'
                ORDER BY requested_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
            """,
            {"started_at": started_at},
        ).mappings().fetchone()

    def get(self, request_id: str) -> Any | None:
        return sql.fetchone(
            self.conn,
            "SELECT * FROM ai_profile_check_requests WHERE id = :id",
            {"id": request_id},
        )

    def complete(
        self,
        *,
        request_id: str,
        status: str,
        finished_at: str,
        error_message: str,
    ) -> None:
        sql.execute(
            self.conn,
            """
            UPDATE ai_profile_check_requests
            SET status = :status, finished_at = :finished_at, error_message = :error_message
            WHERE id = :id
            """,
            {
                "status": status,
                "finished_at": finished_at,
                "error_message": error_message,
                "id": request_id,
            },
        )
