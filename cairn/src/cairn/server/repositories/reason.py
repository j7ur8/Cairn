from __future__ import annotations

from typing import Any

from cairn.server.domain.reason import ReasonFinishState
from cairn.server.repositories import sql


class ReasonRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def get_state(self, project_id: str) -> Any | None:
        return sql.fetchone(
            self.conn,
            "SELECT * FROM project_reason_state WHERE project_id = :project_id",
            {"project_id": project_id},
        )

    def claim_project_reason(
        self,
        project_id: str,
        *,
        worker: str,
        run_id: str | None,
        trigger: str,
        now: str,
    ) -> int:
        cursor = sql.execute(
            self.conn,
            """
            UPDATE projects
            SET reason_worker = :worker,
                reason_run_id = :run_id,
                reason_trigger = :trigger,
                reason_started_at = :now,
                reason_last_heartbeat_at = :now
            WHERE id = :project_id
              AND status = 'active'
              AND reason_worker IS NULL
            """,
            {"worker": worker, "run_id": run_id, "trigger": trigger, "now": now, "project_id": project_id},
        )
        return cursor.rowcount

    def heartbeat_project_reason(self, project_id: str, *, worker: str, now: str) -> int:
        cursor = sql.execute(
            self.conn,
            """
            UPDATE projects
            SET reason_last_heartbeat_at = :now
            WHERE id = :project_id
              AND status = 'active'
              AND reason_worker = :worker
            """,
            {"now": now, "project_id": project_id, "worker": worker},
        )
        return cursor.rowcount

    def release_project_reason(self, project_id: str, *, worker: str) -> int:
        cursor = sql.execute(
            self.conn,
            """
            UPDATE projects
            SET reason_worker = NULL,
                reason_run_id = NULL,
                reason_trigger = NULL,
                reason_started_at = NULL,
                reason_last_heartbeat_at = NULL
            WHERE id = :project_id
              AND status = 'active'
              AND reason_worker = :worker
            """,
            {"project_id": project_id, "worker": worker},
        )
        return cursor.rowcount

    def clear_project_reason(self, project_id: str) -> None:
        sql.execute(
            self.conn,
            """
            UPDATE projects
            SET reason_worker = NULL,
                reason_run_id = NULL,
                reason_trigger = NULL,
                reason_started_at = NULL,
                reason_last_heartbeat_at = NULL
            WHERE id = :project_id
            """,
            {"project_id": project_id},
        )

    def clear_project_reason_if_owner(self, project_id: str, *, worker: str, run_id: str | None) -> int:
        cursor = sql.execute(
            self.conn,
            """
            UPDATE projects
            SET reason_worker = NULL,
                reason_run_id = NULL,
                reason_trigger = NULL,
                reason_started_at = NULL,
                reason_last_heartbeat_at = NULL
            WHERE id = :project_id
              AND reason_worker = :worker
              AND reason_run_id IS NOT DISTINCT FROM :run_id
            """,
            {"project_id": project_id, "worker": worker, "run_id": run_id},
        )
        return cursor.rowcount

    def upsert_state(
        self,
        project_id: str,
        *,
        trigger: str,
        fact_count: int,
        hint_count: int,
        open_intent_count: int,
        state: ReasonFinishState,
        now: str,
    ) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO project_reason_state (
                project_id, trigger, trigger_hash, fact_count, hint_count,
                open_intent_count, outcome, failure_count, last_error,
                next_retry_at, updated_at
            ) VALUES (
                :project_id, :trigger, :trigger_hash, :fact_count, :hint_count,
                :open_intent_count, :outcome, :failure_count, :last_error,
                :next_retry_at, :updated_at
            )
            ON CONFLICT(project_id) DO UPDATE SET
                trigger = excluded.trigger,
                trigger_hash = excluded.trigger_hash,
                fact_count = excluded.fact_count,
                hint_count = excluded.hint_count,
                open_intent_count = excluded.open_intent_count,
                outcome = excluded.outcome,
                failure_count = excluded.failure_count,
                last_error = excluded.last_error,
                next_retry_at = excluded.next_retry_at,
                updated_at = excluded.updated_at
            """,
            {
                "project_id": project_id,
                "trigger": trigger,
                "trigger_hash": state.trigger_hash,
                "fact_count": fact_count,
                "hint_count": hint_count,
                "open_intent_count": open_intent_count,
                "outcome": state.outcome,
                "failure_count": state.failure_count,
                "last_error": state.last_error,
                "next_retry_at": state.next_retry_at,
                "updated_at": now,
            },
        )
