"""JWT auth surface.

Endpoints (all under ``/auth``):
  * ``POST /auth/login``  — email + password -> JWT (public)
  * ``GET  /auth/me``     — current user (requires Bearer)
  * ``POST /auth/users``  — register a new user (superuser only)
  * ``POST /auth/refresh``— issue a new JWT for the current user

Login is rate-limited at the application layer via a small in-memory
counter; replace with a Redis-backed limiter if the deployment grows.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from cairn.observability.metrics import AUTH_LOGINS
from cairn.server.security.deps import (
    current_active_superuser,
    current_user,
    public_user,
)
from cairn.server.security.jwt import issue_token
from cairn.server.security.passwords import hash_password, verify_password
from cairn.server.security.users import UserRow, create, get_by_email


LOG = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


# ---- Schemas ----

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    is_superuser: bool = False


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---- Login rate limiting ----

_LOGIN_WINDOW_SECONDS = 60
_LOGIN_MAX_PER_IP = 10
_login_hits: dict[str, list[float]] = defaultdict(list)
_login_lock = Lock()


def _reset_login_rate_limit_for_tests() -> None:
    """Wipe the in-memory login rate-limit bucket.

    Only intended for the test suite. Production code never reaches
    this; the bucket is intentionally process-local.
    """
    with _login_lock:
        _login_hits.clear()


def _check_login_rate_limit(ip: str) -> None:
    now = time.monotonic()
    with _login_lock:
        bucket = _login_hits[ip]
        bucket[:] = [t for t in bucket if now - t < _LOGIN_WINDOW_SECONDS]
        if len(bucket) >= _LOGIN_MAX_PER_IP:
            AUTH_LOGINS.labels(outcome="rate_limited").inc()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many login attempts; slow down",
            )
        bucket.append(now)


def _client_ip(request: Request) -> str:
    # Best-effort: prefer the first X-Forwarded-For hop, fall back to client.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


# ---- Endpoints ----

@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request) -> LoginResponse:
    ip = _client_ip(request)
    _check_login_rate_limit(ip)
    user = get_by_email(body.email)
    if user is None or not verify_password(body.password, user.hashed_password):
        # Constant-time-ish: always hash a dummy if no user, to avoid timing oracle.
        if user is None:
            verify_password(body.password, "$2b$12$" + "a" * 53)
        AUTH_LOGINS.labels(outcome="bad_credentials").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )
    if not user.is_active:
        AUTH_LOGINS.labels(outcome="inactive").inc()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user is inactive",
        )
    token = issue_token(user.id, extra_claims={"email": user.email})
    AUTH_LOGINS.labels(outcome="success").inc()
    LOG.info("user login user_id=%s ip=%s", user.id, ip)
    return LoginResponse(access_token=token, user=public_user(user))


@router.get("/me")
def me(user: Annotated[UserRow, Depends(current_user)]) -> dict:
    return public_user(user)


@router.post("/users", status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    _superuser: Annotated[UserRow, Depends(current_active_superuser)],
) -> dict:
    if get_by_email(body.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="email already registered",
        )
    user = create(body.email, hash_password(body.password), is_superuser=body.is_superuser)
    LOG.info(
        "user registered user_id=%s is_superuser=%s by=%s",
        user.id, user.is_superuser, _superuser.id,
    )
    return public_user(user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(user: Annotated[UserRow, Depends(current_user)]) -> TokenResponse:
    token = issue_token(user.id, extra_claims={"email": user.email})
    return TokenResponse(access_token=token)
