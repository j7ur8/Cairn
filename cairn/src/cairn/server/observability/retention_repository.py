from __future__ import annotations

from typing import Any

from cairn.server.repositories import sql


class LlmRetentionRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def execution_ids_older_than(self, cutoff_iso: str) -> list[str]:
        rows = sql.fetchall(
            self.conn,
            "SELECT id FROM llm_executions WHERE started_at < :cutoff",
            {"cutoff": cutoff_iso},
        )
        return [row["id"] for row in rows]

    def delete_executions_older_than(self, cutoff_iso: str) -> int:
        cur = sql.execute(
            self.conn,
            "DELETE FROM llm_executions WHERE started_at < :cutoff",
            {"cutoff": cutoff_iso},
        )
        return cur.rowcount
