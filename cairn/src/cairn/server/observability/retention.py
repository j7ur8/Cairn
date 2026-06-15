"""Retention sweep for LLM execution observability data."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import yaml

from cairn.server import db
from cairn.server.observability.event_repository import LlmEventRepository
from cairn.server.observability.retention_repository import LlmRetentionRepository

LOG = logging.getLogger(__name__)

DEFAULT_RETENTION_HOURS = 24 * 14  # 14 days
DEFAULT_RETENTION_INTERVAL_SECONDS = 6 * 60 * 60  # 6 hours


def retention_hours() -> int:
    """Resolve the retention window from config.yaml observability settings."""
    from cairn.server.runtime_config import dispatch_config_path

    path = dispatch_config_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    observability = data.get("observability") if isinstance(data, dict) else None
    raw = observability.get("retention_days") if isinstance(observability, dict) else None
    if raw is None:
        return DEFAULT_RETENTION_HOURS
    try:
        days = int(raw)
    except (TypeError, ValueError):
        LOG.warning(
            "observability.retention_days=%r is not an int in %s; using default %s",
            raw,
            path,
            DEFAULT_RETENTION_HOURS,
        )
        return DEFAULT_RETENTION_HOURS
    if days <= 0:
        LOG.warning(
            "observability.retention_days=%r must be > 0 in %s; using default %s",
            raw,
            path,
            DEFAULT_RETENTION_HOURS,
        )
        return DEFAULT_RETENTION_HOURS
    return days * 24


def _cutoff_iso(hours: int) -> str:
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


def prune_older_than(conn: Any, cutoff_iso: str) -> int:
    """Delete executions older than ``cutoff_iso`` and return the count."""
    retention = LlmRetentionRepository(conn)
    execution_ids = retention.execution_ids_older_than(cutoff_iso)
    LlmEventRepository(conn).delete_for_executions(execution_ids)
    return retention.delete_executions_older_than(cutoff_iso)


def run_sweep(hours: int | None = None) -> int:
    """One-shot sweep. Returns the number of executions deleted.

    Exposed for tests and operators who want to drive retention
    manually. The async loop calls this on a timer.
    """
    window = hours if hours is not None else retention_hours()
    cutoff = _cutoff_iso(window)
    with db.session_scope() as conn:
        deleted = prune_older_than(conn, cutoff)
    if deleted:
        LOG.info(
            "observability retention sweep removed executions=%s cutoff=%s window_hours=%s",
            deleted,
            cutoff,
            window,
        )
    return deleted


async def retention_loop(stop_event: asyncio.Event, *, interval_seconds: int) -> None:
    """Background loop. Exits when ``stop_event`` is set.

    Spawned by :mod:`cairn.server.app` ``lifespan`` only in
    ``cairn serve`` mode. Sleeps ``interval_seconds`` between sweeps and
    logs the outcome.
    """
    LOG.info(
        "observability retention loop started interval_seconds=%s retention_hours=%s",
        interval_seconds,
        retention_hours(),
    )
    try:
        while not stop_event.is_set():
            try:
                run_sweep()
            except Exception:  # noqa: BLE001 - never let a sweep kill the loop
                LOG.exception("observability retention sweep failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except TimeoutError:
                continue
    finally:
        LOG.info("observability retention loop stopped")
