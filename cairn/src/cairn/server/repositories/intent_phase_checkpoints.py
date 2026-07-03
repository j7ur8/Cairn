from __future__ import annotations

from typing import Any

from cairn.server.repositories import sql

EXPLORE_CONCLUDE_PHASE = "explore_conclude"


class IntentPhaseCheckpointRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def get(self, project_id: str, intent_id: str, phase: str = EXPLORE_CONCLUDE_PHASE) -> Any | None:
        return sql.fetchone(
            self.conn,
            """
            SELECT *
            FROM intent_phase_checkpoints
            WHERE project_id = :project_id
              AND intent_id = :intent_id
              AND phase = :phase
            """,
            {"project_id": project_id, "intent_id": intent_id, "phase": phase},
        )

    def list_for_intents(
        self,
        project_ids: list[str],
        intent_ids: list[str],
        *,
        phase: str = EXPLORE_CONCLUDE_PHASE,
    ) -> list[Any]:
        if not project_ids or not intent_ids:
            return []
        return sql.fetchall(
            self.conn,
            """
            SELECT *
            FROM intent_phase_checkpoints
            WHERE project_id = ANY(:project_ids)
              AND intent_id = ANY(:intent_ids)
              AND phase = :phase
            ORDER BY project_id, intent_id, phase
            """,
            {"project_ids": project_ids, "intent_ids": intent_ids, "phase": phase},
        )

    def upsert(
        self,
        *,
        project_id: str,
        intent_id: str,
        phase: str,
        worker_name: str,
        worker_type: str,
        session_id: str,
        now: str,
    ) -> Any | None:
        return sql.fetchone(
            self.conn,
            """
            INSERT INTO intent_phase_checkpoints (
                project_id, intent_id, phase, worker_name, worker_type,
                session_id, last_error, created_at, updated_at
            ) VALUES (
                :project_id, :intent_id, :phase, :worker_name, :worker_type,
                :session_id, NULL, :now, :now
            )
            ON CONFLICT (project_id, intent_id, phase) DO UPDATE
            SET worker_name = EXCLUDED.worker_name,
                worker_type = EXCLUDED.worker_type,
                session_id = EXCLUDED.session_id,
                last_error = NULL,
                updated_at = EXCLUDED.updated_at
            RETURNING *
            """,
            {
                "project_id": project_id,
                "intent_id": intent_id,
                "phase": phase,
                "worker_name": worker_name,
                "worker_type": worker_type,
                "session_id": session_id,
                "now": now,
            },
        )

    def mark_failed(
        self,
        *,
        project_id: str,
        intent_id: str,
        phase: str,
        last_error: str,
        now: str,
    ) -> Any | None:
        return sql.fetchone(
            self.conn,
            """
            UPDATE intent_phase_checkpoints
            SET last_error = :last_error,
                updated_at = :now
            WHERE project_id = :project_id
              AND intent_id = :intent_id
              AND phase = :phase
            RETURNING *
            """,
            {
                "project_id": project_id,
                "intent_id": intent_id,
                "phase": phase,
                "last_error": last_error,
                "now": now,
            },
        )

    def clear(self, project_id: str, intent_id: str, phase: str = EXPLORE_CONCLUDE_PHASE) -> int:
        cursor = sql.execute(
            self.conn,
            """
            DELETE FROM intent_phase_checkpoints
            WHERE project_id = :project_id
              AND intent_id = :intent_id
              AND phase = :phase
            """,
            {"project_id": project_id, "intent_id": intent_id, "phase": phase},
        )
        return cursor.rowcount
