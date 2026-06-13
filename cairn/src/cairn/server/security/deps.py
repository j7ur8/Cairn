"""FastAPI dependencies for JWT-authenticated routes.

The pattern matches the rest of Cairn: synchronous repository calls, the
``current_user`` dependency reads the ``Authorization: Bearer ...`` header,
verifies the JWT against ``dispatch.yaml`` ``system.auth.jwt_secret``, looks up the user in
PostgreSQL, and returns the public view. Active-user enforcement is the
default; ``current_active_superuser`` adds the superuser check.

Routes that need to stay public (login, register, health, metrics) opt
out of these dependencies explicitly.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cairn.server.security.jwt import JWTError, verify_token
from cairn.server.security.users import UserRow, get_by_id, user_to_public

LOG = logging.getLogger(__name__)
_bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _credentials_to_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> UserRow | None:
    if credentials is None or not credentials.credentials:
        return None
    try:
        claims = verify_token(credentials.credentials)
    except JWTError as exc:
        LOG.info("rejecting request: %s", exc)
        return None
    sub = claims.get("sub")
    if not sub:
        return None
    # Service-account tokens (e.g. the dispatcher's configured API token) are
    # identified by a "role" claim of "service". They do not correspond
    # to a row in the users table, but they are still valid callers and
    # are represented as a synthetic superuser-equivalent user for the
    # purpose of route-level dependencies.
    if claims.get("role") == "service":
        return UserRow(
            id=sub,
            email=f"service:{sub}",
            hashed_password="",
            is_active=True,
            is_superuser=True,
            created_at="",
            updated_at="",
        )
    return get_by_id(sub)


def current_user_optional(
    user: Annotated[UserRow | None, Depends(_credentials_to_user)],
) -> UserRow | None:
    return user


def current_user(
    user: Annotated[UserRow | None, Depends(current_user_optional)],
) -> UserRow:
    if user is None:
        raise _unauthorized("missing or invalid bearer token")
    if not user.is_active:
        raise _unauthorized("user is inactive")
    return user


def current_active_superuser(
    user: Annotated[UserRow, Depends(current_user)],
) -> UserRow:
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="superuser privileges required",
        )
    return user


def public_user(user: UserRow) -> dict:
    return user_to_public(user)
