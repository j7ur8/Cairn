from __future__ import annotations

from typing import Any

from cairn.server.repositories import sql


class LlmExecutionRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def upsert_running(
        self,
        *,
        execution_id: str,
        project_id: str,
        intent_id: str | None,
        task_type: str,
        worker: str,
        started_at: str,
    ) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO llm_executions (
                id, project_id, intent_id, task_type, worker, process_state,
                started_at, ended_at, last_event_at, event_count, bytes_written,
                returncode, timed_out, error_kind, produced_fact_id, created_intent_ids
            ) VALUES (
                :id, :project_id, :intent_id, :task_type, :worker, 'running',
                :started_at, NULL, NULL, 0, 0, NULL, 0, NULL, NULL, NULL
            )
            ON CONFLICT(id) DO UPDATE SET
                project_id = excluded.project_id,
                intent_id = excluded.intent_id,
                task_type = excluded.task_type,
                worker = excluded.worker,
                process_state = 'running',
                started_at = excluded.started_at,
                ended_at = NULL,
                returncode = NULL,
                timed_out = 0,
                error_kind = NULL
            """,
            {
                "id": execution_id,
                "project_id": project_id,
                "intent_id": intent_id,
                "task_type": task_type,
                "worker": worker,
                "started_at": started_at,
            },
        )

    def get(self, execution_id: str, project_id: str | None = None) -> Any | None:
        where = "id = :id"
        params: dict[str, object] = {"id": execution_id}
        if project_id is not None:
            where += " AND project_id = :project_id"
            params["project_id"] = project_id
        return sql.fetchone(self.conn, f"SELECT * FROM llm_executions WHERE {where}", params)

    def list_for_project(self, project_id: str, limit: int) -> list[Any]:
        return sql.fetchall(
            self.conn,
            """
            SELECT
                e.id,
                e.project_id,
                e.intent_id,
                e.task_type,
                e.worker,
                e.process_state,
                e.started_at,
                e.ended_at,
                COALESCE(
                    (SELECT MAX(ev.created_at) FROM llm_execution_events ev WHERE ev.execution_id = e.id),
                    e.last_event_at
                ) AS last_event_at,
                GREATEST(
                    e.event_count::bigint,
                    (SELECT COUNT(*) FROM llm_execution_events ev WHERE ev.execution_id = e.id)
                ) AS event_count,
                GREATEST(
                    e.bytes_written::bigint,
                    COALESCE((SELECT SUM(LENGTH(ev.content)) FROM llm_execution_events ev WHERE ev.execution_id = e.id), 0)::bigint
                ) AS bytes_written,
                e.returncode,
                e.timed_out,
                e.error_kind,
                e.produced_fact_id,
                e.created_intent_ids
            FROM llm_executions e
            WHERE e.project_id = :project_id
            ORDER BY started_at DESC, id DESC
            LIMIT :limit
            """,
            {"project_id": project_id, "limit": limit},
        )

    def finish(
        self,
        *,
        project_id: str,
        execution_id: str,
        process_state: str,
        ended_at: str,
        returncode: int | None,
        timed_out: bool,
        error_kind: str | None,
        produced_fact_id: str | None,
        created_intent_ids: str | None,
    ) -> None:
        sql.execute(
            self.conn,
            """
            UPDATE llm_executions
            SET process_state = :process_state,
                ended_at = :ended_at,
                returncode = :returncode,
                timed_out = :timed_out,
                error_kind = :error_kind,
                produced_fact_id = COALESCE(:produced_fact_id, produced_fact_id),
                created_intent_ids = COALESCE(:created_intent_ids, created_intent_ids)
            WHERE id = :execution_id AND project_id = :project_id
            """,
            {
                "process_state": process_state,
                "ended_at": ended_at,
                "returncode": returncode,
                "timed_out": 1 if timed_out else 0,
                "error_kind": error_kind,
                "produced_fact_id": produced_fact_id,
                "created_intent_ids": created_intent_ids,
                "execution_id": execution_id,
                "project_id": project_id,
            },
        )

    def increment_event_stats(
        self,
        *,
        execution_id: str,
        last_event_at: str,
        event_count: int,
        byte_count: int,
    ) -> None:
        sql.execute(
            self.conn,
            """
            UPDATE llm_executions
            SET last_event_at = :last_event_at,
                event_count = event_count + :event_count,
                bytes_written = bytes_written + :byte_count
            WHERE id = :execution_id
            """,
            {
                "last_event_at": last_event_at,
                "event_count": event_count,
                "byte_count": byte_count,
                "execution_id": execution_id,
            },
        )

    def delete_project(self, project_id: str) -> None:
        sql.execute(
            self.conn,
            "DELETE FROM llm_executions WHERE project_id = :project_id",
            {"project_id": project_id},
        )
