from __future__ import annotations

from typing import Any

from cairn.server.observability.repository_shared import (
    EventViewRows,
    append_event_kind_filter,
    base_event_filter,
)
from cairn.server.observability.usage_repository import LlmUsageRepository
from cairn.server.repositories import sql


class LlmEventViewRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def event_view(
        self,
        project_id: str,
        *,
        execution_id: str | None,
        after: int,
        limit: int,
        event_kinds: list[str] | None,
    ) -> EventViewRows:
        where, params = base_event_filter(
            project_id,
            execution_id=execution_id,
            after=after if after > 0 else None,
        )
        where_sql = " AND ".join(where)
        max_row = sql.fetchone(
            self.conn,
            f"SELECT MAX(sequence) AS last_sequence FROM llm_execution_events WHERE {where_sql}",
            params,
        )
        last_sequence = int(max_row["last_sequence"] or after) if max_row is not None else after

        stat_rows = sql.fetchall(
            self.conn,
            f"""
            SELECT event_kind, COUNT(*) AS count
            FROM llm_execution_events
            WHERE {where_sql}
            GROUP BY event_kind
            """,
            params,
        )
        by_kind = {str(row["event_kind"]): int(row["count"]) for row in stat_rows}

        if event_kinds is not None and not event_kinds:
            rows: list[Any] = []
        else:
            event_where = list(where)
            event_params = dict(params)
            append_event_kind_filter(event_where, event_params, event_kinds)
            rows = sql.fetchall(
                self.conn,
                f"""
                SELECT * FROM llm_execution_events
                WHERE {" AND ".join(event_where)}
                ORDER BY sequence DESC
                LIMIT :limit
                """,
                {**event_params, "limit": limit},
            )
        usage_row, usage_count = LlmUsageRepository(self.conn).latest_usage_activity(
            project_id,
            execution_id=execution_id,
            after=after if after > 0 else None,
        )
        return EventViewRows(
            rows=rows,
            last_sequence=last_sequence,
            by_kind=by_kind,
            usage_row=usage_row,
            usage_count=usage_count,
        )
