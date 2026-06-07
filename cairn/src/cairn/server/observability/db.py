from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

DEFAULT_OBSERVABILITY_DB = Path.home() / ".local" / "share" / "cairn" / "cairn_observability.db"

_db_path: Path | None = None
LOG = logging.getLogger(__name__)

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


def configured_path() -> Path:
    assert _db_path is not None
    return _db_path


def sqlite_status() -> dict[str, Any]:
    path = configured_path()
    with get_conn() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        execution_count = conn.execute("SELECT COUNT(*) AS count FROM llm_executions").fetchone()["count"]
        event_count = conn.execute("SELECT COUNT(*) AS count FROM llm_execution_events").fetchone()["count"]
    wal_path = Path(f"{path}-wal")
    shm_path = Path(f"{path}-shm")
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "wal_size_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
        "shm_size_bytes": shm_path.stat().st_size if shm_path.exists() else 0,
        "journal_mode": journal_mode,
        "busy_timeout_ms": busy_timeout,
        "execution_count": execution_count,
        "event_count": event_count,
    }


def integrity_check() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    return [str(row[0]) for row in rows]


def backup_to(destination: Path) -> Path:
    destination = destination.expanduser()
    if destination.is_dir():
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        destination = destination / f"cairn-observability-{stamp}.sqlite"
    destination.parent.mkdir(parents=True, exist_ok=True)
    assert _db_path is not None
    source = sqlite3.connect(str(_db_path), timeout=5.0)
    target = sqlite3.connect(str(destination))
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    return destination


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    assert _db_path is not None
    conn = sqlite3.connect(str(_db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError as exc:
        lower = str(exc).lower()
        if "file is not a database" not in lower and "disk i/o error" not in lower:
            conn.close()
            raise
        wal_path = Path(f"{_db_path}-wal")
        shm_path = Path(f"{_db_path}-shm")
        LOG.warning(
            "observability sqlite wal setup failed path=%s error=%s wal_exists=%s shm_exists=%s; falling back to DELETE journal mode",
            _db_path,
            exc,
            wal_path.exists(),
            shm_path.exists(),
        )
        conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
