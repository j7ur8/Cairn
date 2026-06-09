from __future__ import annotations

import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from cairn.server.db_migrations import MIGRATIONS
from cairn.server.db_schema import SCHEMA
from cairn.server.sqlite_diagnostics import (
    database_error_detail,
    file_state,
    quick_check as run_quick_check,
    truncate_checkpoint,
)

DEFAULT_DB = Path.home() / ".local" / "share" / "cairn" / "cairn.db"
SQLITE_TIMEOUT_SECONDS = 5.0
SQLITE_BUSY_TIMEOUT_MS = 5000

LOG = logging.getLogger(__name__)

_db_path: Path | None = None
_local = threading.local()


def configure(path: Path) -> None:
    global _db_path
    if _db_path is not None:
        return
    _db_path = path
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # Progressive migration: add projects.proxy_id to databases created
        # before proxies were introduced. SQLite has no ADD COLUMN IF NOT
        # EXISTS, so we introspect via PRAGMA table_info.
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(projects)").fetchall()
        }
        if "proxy_id" not in cols:
            conn.execute(
                "ALTER TABLE projects ADD COLUMN proxy_id TEXT "
                "REFERENCES proxies(id) ON DELETE SET NULL"
            )
        if "reason_run_id" not in cols:
            conn.execute("ALTER TABLE projects ADD COLUMN reason_run_id TEXT")
        if "llm_hidden_event_kinds" not in cols:
            conn.execute(
                "ALTER TABLE projects ADD COLUMN llm_hidden_event_kinds "
                "TEXT NOT NULL DEFAULT '[\"usage\"]'"
            )
        _apply_migrations(conn)


def configured_path() -> Path:
    assert _db_path is not None
    return _db_path


def _apply_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS migration_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL,
            sql TEXT NOT NULL,
            error TEXT NOT NULL,
            occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """
    )
    for version, sql in MIGRATIONS:
        applied = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?",
            (version,),
        ).fetchone()
        if applied is not None:
            continue
        if version == "20260604_005_reason_run_id":
            project_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(projects)").fetchall()
            }
            if "reason_run_id" in project_cols:
                conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
                continue
        try:
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
        except Exception as exc:
            conn.execute(
                "INSERT INTO migration_errors (version, sql, error) VALUES (?, ?, ?)",
                (version, sql, str(exc)),
            )
            raise


def _open_conn() -> sqlite3.Connection:
    assert _db_path is not None
    conn = sqlite3.connect(str(_db_path), timeout=SQLITE_TIMEOUT_SECONDS)
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
            "sqlite wal setup failed path=%s error=%s wal_exists=%s shm_exists=%s; falling back to DELETE journal mode",
            _db_path,
            exc,
            wal_path.exists(),
            shm_path.exists(),
        )
        conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def sqlite_status() -> dict[str, Any]:
    """Return operator-facing SQLite status for health/debug commands."""
    path = configured_path()
    with get_conn() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        quick = run_quick_check(conn)
        migration_error = conn.execute(
            "SELECT version, error, occurred_at FROM migration_errors ORDER BY id DESC LIMIT 1"
        ).fetchone()
        applied_count = conn.execute("SELECT COUNT(*) AS count FROM schema_migrations").fetchone()["count"]
    status = {
        "journal_mode": journal_mode,
        "busy_timeout_ms": busy_timeout,
        "foreign_keys": bool(foreign_keys),
        "quick_check": quick,
        "applied_migrations": applied_count,
        "migration_error": dict(migration_error) if migration_error is not None else None,
    }
    return {**file_state(path), **status}


def quick_check() -> list[str]:
    """Run SQLite PRAGMA quick_check and return every result row."""
    with get_conn() as conn:
        return run_quick_check(conn)


def integrity_check() -> list[str]:
    """Run SQLite PRAGMA integrity_check and return every result row."""
    with get_conn() as conn:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    return [str(row[0]) for row in rows]


def checkpoint_truncate() -> dict[str, Any]:
    """Run PRAGMA wal_checkpoint(TRUNCATE) and return before/after file state."""
    path = configured_path()
    before = file_state(path)
    with get_conn() as conn:
        result = truncate_checkpoint(conn)
    after = file_state(path)
    return {"path": str(path), "before": before, "checkpoint": result, "after": after}


def diagnostic_error(exc: BaseException) -> str:
    """Render a DB error with the configured SQLite file state."""
    return database_error_detail(configured_path(), exc)


def backup_to(destination: Path) -> Path:
    """Create a consistent online backup of the configured database."""
    destination = destination.expanduser()
    if destination.is_dir():
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        destination = destination / f"cairn-{stamp}.sqlite"
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = _thread_conn()
    target = sqlite3.connect(str(destination))
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
    return destination


def _thread_conn() -> sqlite3.Connection:
    assert _db_path is not None
    cached = getattr(_local, "conn", None)
    cached_path = getattr(_local, "path", None)
    if cached is not None and cached_path == _db_path:
        return cached
    if cached is not None:
        try:
            cached.close()
        except Exception:
            pass
    conn = _open_conn()
    _local.conn = conn
    _local.path = _db_path
    return conn


def close_thread_conn() -> None:
    """Close the cached SQLite connection for the current thread."""
    cached = getattr(_local, "conn", None)
    if cached is not None:
        cached.close()
    _local.conn = None
    _local.path = None


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = _thread_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


@contextmanager
def with_immediate_tx() -> Generator[sqlite3.Connection, None, None]:
    """Open a connection and acquire a write lock up front.

    SQLite's default deferred transactions acquire the write lock only
    at the first write statement, which can make multi-step writes fail
    late with SQLITE_BUSY. ``BEGIN IMMEDIATE`` grabs the reserved lock
    before the caller runs any read-modify-write sequence.
    """
    conn = _thread_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
