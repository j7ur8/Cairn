"""Health checks for AI profile snapshots and catalog profiles.

Lives on the dispatcher side because base URL reachability and worker
healthcheck commands require the dispatcher/container network context.
The snapshot/catalog probes are intentionally lightweight and side-effect free:

* api key: a profile secret must be present in YAML / execution config.
* base url: TCP connect to (host, port). 4xx/5xx responses are still
  treated as "reachable" — we only care that the endpoint is up.
* worker type: must be declared in ``dispatch.yaml`` ``workers`` with
  type matching the profile.

Manual UI checks additionally run the selected worker driver's real
healthcheck command in a managed container, after applying the profile's
model/base URL/secret overlay. That keeps the UI verdict aligned with
bootstrap/explore/reason task preflight semantics.
"""
from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

from cairn.shared.dispatch_config import DispatchConfig, WorkerConfig
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.scheduler.ai_overlay import compute_ai_overlay
from cairn.dispatcher.tasks.common import run_healthcheck
from cairn.dispatcher.workers.registry import get_driver
from cairn.shared.protocol_models import (
    AiProfile,
    CANONICAL_AUTH_ENV,
    HealthCheckItem,
    HealthCheckResult,
    ProjectAiProfileSnapshot,
    auth_env_warning,
)

LOG = logging.getLogger(__name__)
PROFILE_HEALTHCHECK_PREVIEW_LIMIT = 240


@dataclass(slots=True)
class ProfileWorkerHealthcheckResult:
    ok: bool
    worker_name: str
    returncode: int
    duration_ms: int
    stdout_preview: str
    stderr_preview: str
    message: str


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


def _check_auth_configured(env_name: str, secret: str | None) -> HealthCheckItem:
    name = "api_key_configured"
    if not env_name:
        return HealthCheckItem(name=name, ok=False, message="api_key_env is empty")
    if secret is None:
        guidance = ""
        canonical = CANONICAL_AUTH_ENV.get("codex") if env_name == "OPENAI_API_KEY" else CANONICAL_AUTH_ENV.get("claudecode") if env_name == "ANTHROPIC_AUTH_TOKEN" else None
        if canonical is not None:
            guidance = (
                f"; define {canonical} directly in dispatch.yaml worker env"
            )
        return HealthCheckItem(
            name=name, ok=False,
            message=f"secret for '{env_name}' is not configured{guidance}",
        )
    if not secret.strip():
        return HealthCheckItem(
            name=name, ok=False,
            message=f"secret for '{env_name}' is configured but empty",
        )
    return HealthCheckItem(name=name, ok=True, message=f"secret configured for '{env_name}'")


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
    cached_secret: str | None = None,
    timeout: float | None = None,
) -> HealthCheckResult:
    """Run the full health check on a stored AI profile snapshot."""
    effective_timeout = timeout if timeout is not None else 1.0
    checks = [
        _check_auth_configured(snapshot.snapshot_api_key_env, cached_secret),
        _check_base_url(snapshot.snapshot_base_url, effective_timeout),
        _check_worker_type(snapshot.snapshot_worker_type, config.workers),
    ]
    ok = all(item.ok for item in checks)
    return HealthCheckResult(ok=ok, checks=checks)


def probe_profile(
    profile: AiProfile,
    *,
    config: DispatchConfig,
    timeout: float | None = None,
) -> HealthCheckResult:
    """Run the health check against a catalog profile row."""
    effective_timeout = timeout if timeout is not None else float(profile.healthcheck_timeout or 1.0)
    checks = [
        _check_auth_configured(profile.api_key_env, profile.sk),
        _check_base_url(profile.base_url, effective_timeout),
        _check_worker_type(profile.worker_type, config.workers),
    ]
    ok = all(item.ok for item in checks)
    return HealthCheckResult(ok=ok, checks=checks)


def run_profile_worker_healthcheck(
    profile: AiProfile,
    *,
    config: DispatchConfig,
    container_manager: ContainerManager,
    cached_secret: str | None = None,
    timeout_seconds: int | None = None,
) -> ProfileWorkerHealthcheckResult:
    """Run the same worker-level healthcheck used before task execution.

    The UI ``Check`` button is meant to answer "will this profile work when
    selected for a task?".  Lightweight env/TCP checks cannot answer that, so
    this builds the profile's normal worker env overlay and executes the
    matching driver's healthcheck command in a dispatcher-managed container.
    """
    effective_timeout = float(profile.healthcheck_timeout or 1.0)
    preflight_checks = [
        _check_auth_configured(profile.api_key_env, cached_secret),
        _check_base_url(profile.base_url, effective_timeout),
        _check_worker_type(profile.worker_type, config.workers),
    ]
    if not all(item.ok for item in preflight_checks):
        message = _format_probe_failure(HealthCheckResult(ok=False, checks=preflight_checks))
        return ProfileWorkerHealthcheckResult(
            ok=False,
            worker_name="-",
            returncode=1,
            duration_ms=0,
            stdout_preview="",
            stderr_preview="",
            message=message,
        )

    candidates = [worker for worker in config.workers if worker.type == profile.worker_type]
    if not candidates:
        message = f"worker_type '{profile.worker_type}' is not declared in dispatch.yaml workers"
        return ProfileWorkerHealthcheckResult(
            ok=False,
            worker_name="-",
            returncode=1,
            duration_ms=0,
            stdout_preview="",
            stderr_preview="",
            message=message,
        )

    snapshot = _profile_to_snapshot(profile)
    overlay = compute_ai_overlay(snapshot, cached_secret=cached_secret)
    worker = _choose_profile_worker(candidates, overlay)
    if worker is None:
        missing = _missing_required_overlay_keys(candidates, overlay)
        message = "no matching worker has required profile env"
        if missing:
            message += ": " + ", ".join(missing)
        return ProfileWorkerHealthcheckResult(
            ok=False,
            worker_name="-",
            returncode=1,
            duration_ms=0,
            stdout_preview="",
            stderr_preview="",
            message=message,
        )

    driver = get_driver(worker.type)
    container_name = container_manager.create_startup_container()
    effective_timeout_seconds = timeout_seconds or config.runtime.healthcheck_timeout
    try:
        healthcheck = run_healthcheck(
            container_manager,
            container_name,
            worker,
            driver.build_healthcheck(worker),
            timeout_seconds=effective_timeout_seconds,
            tty=driver.requires_tty(),
        )
    finally:
        container_manager.remove_container(container_name, force=True)

    result = healthcheck.result
    ok = result.returncode == 0
    stdout_preview = _preview(result.stdout)
    stderr_preview = _preview(result.stderr)
    message = _format_worker_healthcheck_message(
        ok=ok,
        worker_name=worker.name,
        returncode=result.returncode,
        duration_ms=healthcheck.duration_ms,
        stdout_preview=stdout_preview,
        stderr_preview=stderr_preview,
        timed_out=result.timed_out,
    )
    return ProfileWorkerHealthcheckResult(
        ok=ok,
        worker_name=worker.name,
        returncode=result.returncode,
        duration_ms=healthcheck.duration_ms,
        stdout_preview=stdout_preview,
        stderr_preview=stderr_preview,
        message=message,
    )


def _profile_to_snapshot(profile: AiProfile) -> ProjectAiProfileSnapshot:
    return ProjectAiProfileSnapshot(
        profile_id=profile.id,
        task_type="bootstrap",
        role="primary",
        position=0,
        snapshot_name=profile.name,
        snapshot_worker_type=profile.worker_type,
        snapshot_provider=profile.provider,
        snapshot_base_url=profile.base_url,
        snapshot_model=profile.model,
        snapshot_reasoning_type=profile.model_reasoning_effort,
        snapshot_api_key_env=profile.api_key_env,
    )


def _choose_profile_worker(
    candidates: list[WorkerConfig],
    overlay: dict[str, str],
) -> WorkerConfig | None:
    for candidate in candidates:
        worker = candidate.model_copy(update={"env": {**candidate.env, **overlay}})
        if not _missing_env_keys(worker):
            return worker
    return None


def _missing_required_overlay_keys(
    candidates: list[WorkerConfig],
    overlay: dict[str, str],
) -> list[str]:
    missing: set[str] = set()
    for candidate in candidates:
        worker = candidate.model_copy(update={"env": {**candidate.env, **overlay}})
        missing.update(_missing_env_keys(worker))
    return sorted(missing)


def _missing_env_keys(worker: WorkerConfig) -> list[str]:
    try:
        WorkerConfig.model_validate(worker.model_dump())
    except ValueError as exc:
        message = str(exc)
        marker = "missing env keys: "
        if marker in message:
            return [item.strip() for item in message.split(marker, 1)[1].split(",") if item.strip()]
        return [message]
    return []


def _format_probe_failure(health: HealthCheckResult) -> str:
    bad = [item for item in health.checks if not item.ok]
    return "; ".join(f"{item.name}={item.message or 'fail'}" for item in bad) or "profile preflight failed"


def _format_worker_healthcheck_message(
    *,
    ok: bool,
    worker_name: str,
    returncode: int,
    duration_ms: int,
    stdout_preview: str,
    stderr_preview: str,
    timed_out: bool,
) -> str:
    status = "ok" if ok else "failed"
    bits = [
        f"worker healthcheck {status}",
        f"worker={worker_name}",
        f"code={returncode}",
        f"duration_ms={duration_ms}",
    ]
    if timed_out:
        bits.append("timed_out=true")
    if stdout_preview:
        bits.append(f"stdout={stdout_preview}")
    if stderr_preview:
        bits.append(f"stderr={stderr_preview}")
    return "; ".join(bits)


def _preview(value: str, limit: int = PROFILE_HEALTHCHECK_PREVIEW_LIMIT) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def profile_warnings(
    worker_type: str,
    api_key_env: str,
) -> list[str]:
    """Surface non-blocking UI warnings (e.g. auth-var naming)."""
    warning = auth_env_warning(worker_type, api_key_env)
    return [warning] if warning else []


__all__ = [
    "probe_profile",
    "probe_snapshot",
    "run_profile_worker_healthcheck",
    "profile_warnings",
    "CANONICAL_AUTH_ENV",
]
