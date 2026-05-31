from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

DEFAULT_OBSERVABILITY_DB = Path.home() / ".local" / "share" / "cairn" / "cairn_observability.db"

_db_path: Path | None = None

SCHEMA = """\
CREATE TABLE IF NOT EXISTS llm_executions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    intent_id TEXT NULL,
    task_type TEXT NOT NULL,
    worker TEXT NOT NULL,
    process_state TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NULL,
    last_event_at TEXT NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    bytes_written INTEGER NOT NULL DEFAULT 0,
    returncode INTEGER NULL,
    timed_out INTEGER NOT NULL DEFAULT 0,
    error_kind TEXT NULL,
    produced_fact_id TEXT NULL,
    created_intent_ids TEXT NULL
);

CREATE TABLE IF NOT EXISTS llm_execution_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    intent_id TEXT NULL,
    task_type TEXT NOT NULL,
    worker TEXT NOT NULL,
    phase TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    stream TEXT NOT NULL,
    content TEXT NOT NULL,
    truncated INTEGER NOT NULL DEFAULT 0,
    redacted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_executions_project_started
    ON llm_executions (project_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_execution_events_project_sequence
    ON llm_execution_events (project_id, sequence);
CREATE INDEX IF NOT EXISTS idx_llm_execution_events_execution_sequence
    ON llm_execution_events (execution_id, sequence);
"""


def configure(path: Path = DEFAULT_OBSERVABILITY_DB) -> None:
    global _db_path
    if _db_path is not None:
        return
    _db_path = path.expanduser()
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    assert _db_path is not None
    conn = sqlite3.connect(str(_db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
