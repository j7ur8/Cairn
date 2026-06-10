"""User repository over the configured database layer.

``UserRow`` is a lightweight named tuple the auth router and FastAPI
dependency share. The repository talks to the same transaction context
manager everything else uses.
"""
from __future__ import annotations

from typing import Any


from cairn.server import db
from cairn.server.repositories.users import UserRecord, UserRepository


UserRow = UserRecord


def get_by_email(email: str) -> UserRow | None:
    with db.session_scope() as conn:
        return UserRepository(conn).get_by_email(email)


def get_by_id(user_id: str) -> UserRow | None:
    with db.session_scope() as conn:
        return UserRepository(conn).get_by_id(user_id)


def create(email: str, hashed_password: str, *, is_superuser: bool = False) -> UserRow:
    with db.session_scope() as conn:
        return UserRepository(conn).create(email, hashed_password, is_superuser=is_superuser)


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
    """Create the initial superuser from dispatch.yaml if neither exists yet.

    Returns the new user on success, ``None`` if the env is unset or the
    superuser already exists. The password is consumed once and never
    echoed in logs.
    """
    from cairn.server.runtime_config import system_config
    initial_admin = system_config().initial_admin
    email = initial_admin.email.strip().lower()
    password = initial_admin.password
    if not email or not password:
        return None
    if get_by_email(email) is not None:
        return None
    from cairn.server.security.passwords import hash_password
    return create(email, hash_password(password), is_superuser=True)
