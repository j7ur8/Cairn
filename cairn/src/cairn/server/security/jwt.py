"""JWT issue/verify for the Cairn API."""
from __future__ import annotations

import time
import uuid
from typing import Any

import jwt


DEFAULT_LIFETIME_SECONDS = 60 * 60  # 1 hour


class JWTError(RuntimeError):
    """Raised on issue or verify failure."""


def _signing_key() -> str:
    from cairn.server.runtime_config import system_config
    key = system_config().auth.jwt_secret
    if not key:
        raise JWTError("dispatch.yaml system.auth.jwt_secret is not set; cannot issue tokens")
    return key


def issue_token(
    subject: str,
    *,
    lifetime_seconds: int = DEFAULT_LIFETIME_SECONDS,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Mint a JWT for ``subject`` (typically a user id or service-account id)."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "nbf": now,
        "exp": now + lifetime_seconds,
        "jti": uuid.uuid4().hex,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, _signing_key(), algorithm="HS256")


def verify_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises :class:`JWTError` on any failure."""
    if not token:
        raise JWTError("empty token")
    try:
        return jwt.decode(token, _signing_key(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise JWTError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise JWTError(f"invalid token: {exc}") from exc
