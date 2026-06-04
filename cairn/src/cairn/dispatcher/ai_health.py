"""Best-effort health probe for AI profile snapshots.

Lives on the dispatcher side because the *auth env var* and the *base URL*
are operator-side secrets / network endpoints that the server cannot see.
The probe is intentionally lightweight and side-effect free:

* api key env: ``os.environ.get(name)`` must be set and non-empty.
* base url: TCP connect to (host, port). 4xx/5xx responses are still
  treated as "reachable" — we only care that the endpoint is up.
* worker type: must be declared in ``dispatch.yaml`` ``workers`` with
  type matching the profile.

Probes are best-effort. They never raise; the caller decides what to do
with a failed check (typically: mark the row ``available=false``).
"""
from __future__ import annotations

import logging
import os
import socket
from typing import Iterable
from urllib.parse import urlparse

from cairn.dispatcher.config import DispatchConfig, WorkerConfig
from cairn.server.models import (
    CANONICAL_AUTH_ENV,
    HealthCheckItem,
    HealthCheckResult,
    ProjectAiProfileSnapshot,
    auth_env_warning,
)

LOG = logging.getLogger(__name__)


def _probe_http_url(url: str, timeout: float) -> tuple[bool, str]:
    """Best-effort reachability probe for an AI provider base URL.

    Does a TCP connect to (host, port) so the probe does not depend on
    path correctness, auth, or the upstream API's HTTP semantics. Any
    successful connect (including a 4xx/5xx from the server) is treated
    as "reachable". Returns ``(ok, reason)``.
    """
    if not url:
        return True, ""
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False, "base_url has no host"
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except (OSError, socket.timeout) as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _check_auth_env(env_name: str) -> HealthCheckItem:
    name = "api_key_env_present"
    if not env_name:
        return HealthCheckItem(name=name, ok=False, message="api_key_env is empty")
    value = os.environ.get(env_name)
    if value is None:
        guidance = ""
        canonical = CANONICAL_AUTH_ENV.get("codex") if env_name == "OPENAI_API_KEY" else CANONICAL_AUTH_ENV.get("claudecode") if env_name == "ANTHROPIC_AUTH_TOKEN" else None
        if canonical is not None:
            guidance = (
                f"; define {canonical} directly in .env / compose on the dispatcher host"
            )
        return HealthCheckItem(
            name=name, ok=False,
            message=f"env var '{env_name}' is not set on the dispatcher host{guidance}",
        )
    if not value.strip():
        return HealthCheckItem(
            name=name, ok=False,
            message=f"env var '{env_name}' is set but empty",
        )
    return HealthCheckItem(name=name, ok=True, message=f"env var '{env_name}' resolved")


def _check_base_url(base_url: str, timeout: float) -> HealthCheckItem:
    name = "base_url_reachable"
    if not base_url:
        # Optional field; absence is fine.
        return HealthCheckItem(name=name, ok=True, message="no base_url declared")
    ok, reason = _probe_http_url(base_url, timeout)
    if not ok:
        return HealthCheckItem(name=name, ok=False, message=reason)
    return HealthCheckItem(name=name, ok=True, message="TCP connect succeeded")


def _check_worker_type(
    worker_type: str,
    workers: Iterable[WorkerConfig],
) -> HealthCheckItem:
    name = "worker_type_declared"
    matching = [w for w in workers if w.type == worker_type]
    if not matching:
        return HealthCheckItem(
            name=name, ok=False,
            message=f"worker_type '{worker_type}' is not declared in dispatch.yaml workers",
        )
    return HealthCheckItem(
        name=name, ok=True,
        message=f"{len(matching)} dispatch.yaml worker(s) of type '{worker_type}'",
    )


def probe_snapshot(
    snapshot: ProjectAiProfileSnapshot,
    *,
    config: DispatchConfig,
    timeout: float | None = None,
) -> HealthCheckResult:
    """Run the full health check on a stored AI profile snapshot."""
    effective_timeout = timeout if timeout is not None else 1.0
    checks = [
        _check_auth_env(snapshot.snapshot_api_key_env),
        _check_base_url(snapshot.snapshot_base_url, effective_timeout),
        _check_worker_type(snapshot.snapshot_worker_type, config.workers),
    ]
    ok = all(item.ok for item in checks)
    return HealthCheckResult(ok=ok, checks=checks)


def profile_warnings(
    worker_type: str,
    api_key_env: str,
) -> list[str]:
    """Surface non-blocking UI warnings (e.g. auth-var naming)."""
    warning = auth_env_warning(worker_type, api_key_env)
    return [warning] if warning else []


__all__ = [
    "probe_snapshot",
    "profile_warnings",
    "CANONICAL_AUTH_ENV",
]
