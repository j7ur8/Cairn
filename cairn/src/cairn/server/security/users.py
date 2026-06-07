"""User repository over the existing sqlite3 layer.

A thin module: no SQLAlchemy, no async. ``UserRow`` is a lightweight named
tuple the auth router and FastAPI dependency share. The repository talks
to the same ``get_conn()`` context manager everything else uses.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import sqlite3

from cairn.server.db import get_conn


@dataclass(slots=True, frozen=True)
class UserRow:
    id: str
    email: str
    hashed_password: str
    is_active: bool
    is_superuser: bool
    created_at: str
    updated_at: str


def _row_to_user(row: sqlite3.Row) -> UserRow:
    return UserRow(
        id=row["id"],
        email=row["email"],
        hashed_password=row["hashed_password"],
        is_active=bool(row["is_active"]),
        is_superuser=bool(row["is_superuser"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_by_email(email: str) -> UserRow | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower(),)
        ).fetchone()
    return _row_to_user(row) if row else None


def get_by_id(user_id: str) -> UserRow | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(row) if row else None


def create(email: str, hashed_password: str, *, is_superuser: bool = False) -> UserRow:
    now = _utcnow()
    user_id = f"u_{uuid.uuid4().hex[:12]}"
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (
                id, email, hashed_password, is_active, is_superuser,
                created_at, updated_at
            ) VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            (user_id, email.lower(), hashed_password, 1 if is_superuser else 0, now, now),
        )
    return UserRow(
        id=user_id,
        email=email.lower(),
        hashed_password=hashed_password,
        is_active=True,
        is_superuser=is_superuser,
        created_at=now,
        updated_at=now,
    )


def user_to_public(user: UserRow) -> dict[str, Any]:
    """Return the JSON-friendly view used in API responses."""
    return {
        "id": user.id,
        "email": user.email,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "created_at": user.created_at,
    }


def bootstrap_superuser_if_configured() -> UserRow | None:
    """Create the initial superuser from env if neither exists yet.

    Reads ``CAIRN_INITIAL_ADMIN_EMAIL`` and ``CAIRN_INITIAL_ADMIN_PASSWORD``.
    Returns the new user on success, ``None`` if the env is unset or the
    superuser already exists. The password is consumed once and never
    echoed in logs.
    """
    email = os.environ.get("CAIRN_INITIAL_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("CAIRN_INITIAL_ADMIN_PASSWORD", "")
    if not email or not password:
        return None
    if get_by_email(email) is not None:
        return None
    from cairn.server.security.passwords import hash_password
    return create(email, hash_password(password), is_superuser=True)


# Late import to avoid a circular dependency at module load time.
import os
