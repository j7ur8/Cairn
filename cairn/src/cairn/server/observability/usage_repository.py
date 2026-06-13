from __future__ import annotations

from typing import Any

from cairn.server.observability.repository_shared import base_event_filter
from cairn.server.repositories import sql


class LlmUsageRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def latest_usage_activity(
        self,
        project_id: str,
        *,
        execution_id: str | None,
        after: int | None,
    ) -> tuple[Any | None, int]:
        where, params = base_event_filter(project_id, execution_id=execution_id, after=after)
        return self.latest_usage_activity_for_where(" AND ".join(where), params)

    def latest_usage_activity_for_where(self, where_sql: str, params: dict[str, object]) -> tuple[Any | None, int]:
        usage_count_row = sql.fetchone(
            self.conn,
            f"SELECT COUNT(*) AS count FROM llm_execution_events WHERE {where_sql} AND event_kind = 'usage'",
            params,
        )
        usage_count = int(usage_count_row["count"] or 0) if usage_count_row is not None else 0
        if usage_count <= 0:
            return None, usage_count
        row = sql.fetchone(
            self.conn,
            f"""
            SELECT * FROM llm_execution_events
            WHERE {where_sql} AND event_kind = 'usage'
            ORDER BY sequence DESC
            LIMIT 1
            """,
            params,
        )
        return row, usage_count
