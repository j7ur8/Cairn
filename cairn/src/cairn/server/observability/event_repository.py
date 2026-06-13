from __future__ import annotations

from typing import Any

from sqlalchemy import text

from cairn.server.observability.repository_shared import (
    IncrementalEventRows,
    append_event_kind_filter,
    base_event_filter,
)
from cairn.server.repositories import sql


class LlmEventRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def delete_project(self, project_id: str) -> None:
        sql.execute(
            self.conn,
            "DELETE FROM llm_execution_events WHERE project_id = :project_id",
            {"project_id": project_id},
        )

    def list_project_events(self, project_id: str, after: int, limit: int, *, tail: bool = False) -> list[Any]:
        if tail:
            return list(
                reversed(
                    sql.fetchall(
                        self.conn,
                        """
                        SELECT * FROM llm_execution_events
                        WHERE project_id = :project_id
                        ORDER BY sequence DESC
                        LIMIT :limit
                        """,
                        {"project_id": project_id, "limit": limit},
                    )
                )
            )
        return sql.fetchall(
            self.conn,
            """
            SELECT * FROM llm_execution_events
            WHERE project_id = :project_id AND sequence > :after
            ORDER BY sequence ASC
            LIMIT :limit
            """,
            {"project_id": project_id, "after": after, "limit": limit},
        )

    def list_execution_events(
        self,
        project_id: str,
        execution_id: str,
        after: int,
        limit: int,
        *,
        tail: bool = False,
    ) -> list[Any]:
        if tail:
            return list(
                reversed(
                    sql.fetchall(
                        self.conn,
                        """
                        SELECT * FROM llm_execution_events
                        WHERE project_id = :project_id AND execution_id = :execution_id
                        ORDER BY sequence DESC
                        LIMIT :limit
                        """,
                        {"project_id": project_id, "execution_id": execution_id, "limit": limit},
                    )
                )
            )
        return sql.fetchall(
            self.conn,
            """
            SELECT * FROM llm_execution_events
            WHERE project_id = :project_id AND execution_id = :execution_id AND sequence > :after
            ORDER BY sequence ASC
            LIMIT :limit
            """,
            {"project_id": project_id, "execution_id": execution_id, "after": after, "limit": limit},
        )

    def list_incremental_events(
        self,
        project_id: str,
        *,
        execution_id: str | None,
        after: int,
        limit: int,
        event_kinds: list[str] | None,
    ) -> IncrementalEventRows:
        where, params = base_event_filter(project_id, execution_id=execution_id, after=after)
        max_row = sql.fetchone(
            self.conn,
            f"SELECT MAX(sequence) AS last_sequence FROM llm_execution_events WHERE {' AND '.join(where)}",
            params,
        )
        last_sequence = int(max_row["last_sequence"] or after) if max_row is not None else after
        if event_kinds is not None and not event_kinds:
            return IncrementalEventRows(rows=[], last_sequence=last_sequence)

        event_where = list(where)
        event_params = dict(params)
        append_event_kind_filter(event_where, event_params, event_kinds)
        rows = sql.fetchall(
            self.conn,
            f"""
            SELECT * FROM llm_execution_events
            WHERE {" AND ".join(event_where)}
            ORDER BY sequence ASC
            LIMIT :limit
            """,
            {**event_params, "limit": limit},
        )
        return IncrementalEventRows(rows=rows, last_sequence=last_sequence)

    def insert_event_rows(self, rows: list[dict[str, Any]]) -> list[Any]:
        if not rows:
            return []
        placeholders: list[str] = []
        params: dict[str, Any] = {}
        fields = (
            "execution_id",
            "project_id",
            "intent_id",
            "task_type",
            "worker",
            "phase",
            "event_kind",
            "stream",
            "content",
            "truncated",
            "redacted",
            "created_at",
        )
        for index, row in enumerate(rows):
            names: list[str] = []
            for field in fields:
                key = f"{field}_{index}"
                names.append(f":{key}")
                params[key] = row[field]
            placeholders.append(f"({', '.join(names)})")
        result = self.conn.execute(
            text(
                f"""
                INSERT INTO llm_execution_events (
                    execution_id, project_id, intent_id, task_type, worker, phase,
                    event_kind, stream, content, truncated, redacted, created_at
                ) VALUES {", ".join(placeholders)}
                RETURNING *
                """
            ),
            params,
        )
        return list(result.mappings().fetchall())

    def has_process_end_event(self, execution_id: str) -> bool:
        row = sql.fetchone(
            self.conn,
            """
            SELECT 1 FROM llm_execution_events
            WHERE execution_id = :execution_id AND event_kind = 'process_end'
            LIMIT 1
            """,
            {"execution_id": execution_id},
        )
        return row is not None

    def insert_process_end_event(
        self,
        *,
        execution: Any,
        content: str,
        created_at: str,
    ) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO llm_execution_events (
                execution_id, project_id, intent_id, task_type, worker, phase,
                event_kind, stream, content, truncated, redacted, created_at
            ) VALUES (
                :execution_id, :project_id, :intent_id, :task_type, :worker,
                'finish', 'process_end', 'system', :content, 0, 0, :created_at
            )
            """,
            {
                "execution_id": execution["id"],
                "project_id": execution["project_id"],
                "intent_id": execution["intent_id"],
                "task_type": execution["task_type"],
                "worker": execution["worker"],
                "content": content,
                "created_at": created_at,
            },
        )

    def delete_for_executions(self, execution_ids: list[str]) -> None:
        for execution_id in execution_ids:
            sql.execute(
                self.conn,
                "DELETE FROM llm_execution_events WHERE execution_id = :execution_id",
                {"execution_id": execution_id},
            )
