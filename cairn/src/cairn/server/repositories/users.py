from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cairn.server.repositories import sql


@dataclass(slots=True, frozen=True)
class UserRecord:
    id: str
    email: str
    hashed_password: str
    is_active: bool
    is_superuser: bool
    created_at: str
    updated_at: str


def _utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_user(row: Any) -> UserRecord:
    return UserRecord(
        id=row["id"],
        email=row["email"],
        hashed_password=row["hashed_password"],
        is_active=bool(row["is_active"]),
        is_superuser=bool(row["is_superuser"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class UserRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def get_by_email(self, email: str) -> UserRecord | None:
        row = sql.fetchone(
            self.conn,
            "SELECT * FROM users WHERE email = :email",
            {"email": email.lower()},
        )
        return _row_to_user(row) if row else None

    def get_by_id(self, user_id: str) -> UserRecord | None:
        row = sql.fetchone(self.conn, "SELECT * FROM users WHERE id = :user_id", {"user_id": user_id})
        return _row_to_user(row) if row else None

    def create(self, email: str, hashed_password: str, *, is_superuser: bool = False) -> UserRecord:
        now = _utcnow()
        user_id = f"u_{uuid.uuid4().hex[:12]}"
        sql.execute(
            self.conn,
            """
            INSERT INTO users (
                id, email, hashed_password, is_active, is_superuser,
                created_at, updated_at
            ) VALUES (
                :user_id, :email, :hashed_password, 1, :is_superuser,
                :created_at, :updated_at
            )
            """,
            {
                "user_id": user_id,
                "email": email.lower(),
                "hashed_password": hashed_password,
                "is_superuser": 1 if is_superuser else 0,
                "created_at": now,
                "updated_at": now,
            },
        )
        return UserRecord(
            id=user_id,
            email=email.lower(),
            hashed_password=hashed_password,
            is_active=True,
            is_superuser=is_superuser,
            created_at=now,
            updated_at=now,
        )
