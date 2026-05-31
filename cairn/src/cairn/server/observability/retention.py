from __future__ import annotations

import sqlite3


def prune_older_than(conn: sqlite3.Connection, cutoff_iso: str) -> None:
    rows = conn.execute(
        "SELECT id FROM llm_executions WHERE started_at < ?",
        (cutoff_iso,),
    ).fetchall()
    execution_ids = [row["id"] for row in rows]
    for execution_id in execution_ids:
        conn.execute("DELETE FROM llm_execution_events WHERE execution_id = ?", (execution_id,))
    conn.execute("DELETE FROM llm_executions WHERE started_at < ?", (cutoff_iso,))
