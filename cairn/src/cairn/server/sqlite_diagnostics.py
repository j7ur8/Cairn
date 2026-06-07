from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


TRANSIENT_DATABASE_ERROR_MARKERS = (
    "database disk image is malformed",
    "disk i/o error",
    "file is not a database",
    "database is locked",
)


def file_state(path: Path) -> dict[str, Any]:
    wal_path = Path(f"{path}-wal")
    shm_path = Path(f"{path}-shm")
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": _size(path),
        "mtime": _mtime(path),
        "wal_path": str(wal_path),
        "wal_exists": wal_path.exists(),
        "wal_size_bytes": _size(wal_path),
        "wal_mtime": _mtime(wal_path),
        "shm_path": str(shm_path),
        "shm_exists": shm_path.exists(),
        "shm_size_bytes": _size(shm_path),
        "shm_mtime": _mtime(shm_path),
    }


def quick_check(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("PRAGMA quick_check").fetchall()
    return [str(row[0]) for row in rows]


def passive_checkpoint(conn: sqlite3.Connection) -> dict[str, int | str]:
    row = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
    return _checkpoint_row(row)


def truncate_checkpoint(conn: sqlite3.Connection) -> dict[str, int | str]:
    row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    return _checkpoint_row(row)


def is_transient_database_error(exc: BaseException) -> bool:
    if not isinstance(exc, sqlite3.DatabaseError):
        return False
    text = str(exc).lower()
    return any(marker in text for marker in TRANSIENT_DATABASE_ERROR_MARKERS)


def database_error_detail(path: Path, exc: BaseException) -> str:
    state = file_state(path)
    return (
        f"{type(exc).__name__}: {exc}; "
        f"path={state['path']} exists={state['exists']} size={state['size_bytes']} "
        f"wal_exists={state['wal_exists']} wal_size={state['wal_size_bytes']} "
        f"shm_exists={state['shm_exists']} shm_size={state['shm_size_bytes']}"
    )


def _checkpoint_row(row: Any) -> dict[str, int | str]:
    if row is None:
        return {"busy": -1, "log": -1, "checkpointed": -1}
    values = list(row)
    if len(values) < 3:
        return {"busy": -1, "log": -1, "checkpointed": -1, "raw": repr(row)}
    return {
        "busy": int(values[0]),
        "log": int(values[1]),
        "checkpointed": int(values[2]),
    }


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None
