"""Retention sweep for LLM execution observability data.

A single ``prune_older_than`` helper is wrapped by an async loop
that the FastAPI lifespan starts in ``cairn serve`` mode. The loop
runs every :data:`DEFAULT_RETENTION_INTERVAL_SECONDS` seconds and
trims rows from ``llm_executions`` (and their child
``llm_execution_events``) older than the configured cutoff.

The CLI (``cairn dispatch`` etc.) does *not* start the loop -
operators using the CLI manage retention externally (cron + the
exposed helper) to avoid background threads in short-lived
processes.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from cairn.server.observability import db as observability_db


LOG = logging.getLogger(__name__)

DEFAULT_RETENTION_HOURS = 24 * 14  # 14 days
DEFAULT_RETENTION_INTERVAL_SECONDS = 6 * 60 * 60  # 6 hours


def retention_hours() -> int:
    """Resolve the retention window from env, falling back to the default."""
    raw = os.environ.get("OBSERVABILITY_RETENTION_HOURS")
    if not raw:
        return DEFAULT_RETENTION_HOURS
    try:
        value = int(raw)
    except ValueError:
        LOG.warning(
            "OBSERVABILITY_RETENTION_HOURS=%r is not an int; using default %s",
            raw,
            DEFAULT_RETENTION_HOURS,
        )
        return DEFAULT_RETENTION_HOURS
    if value <= 0:
        LOG.warning(
            "OBSERVABILITY_RETENTION_HOURS=%r must be > 0; using default %s",
            raw,
            DEFAULT_RETENTION_HOURS,
        )
        return DEFAULT_RETENTION_HOURS
    return value


def retention_interval_seconds() -> int:
    raw = os.environ.get("OBSERVABILITY_RETENTION_INTERVAL_SECONDS")
    if not raw:
        return DEFAULT_RETENTION_INTERVAL_SECONDS
    try:
        value = int(raw)
    except ValueError:
        LOG.warning(
            "OBSERVABILITY_RETENTION_INTERVAL_SECONDS=%r is not an int; using default %s",
            raw,
            DEFAULT_RETENTION_INTERVAL_SECONDS,
        )
        return DEFAULT_RETENTION_INTERVAL_SECONDS
    if value < 60:
        # Guard against typos like "6" being interpreted as 6s.
        LOG.warning(
            "OBSERVABILITY_RETENTION_INTERVAL_SECONDS=%r too small (<60s); using default %s",
            raw,
            DEFAULT_RETENTION_INTERVAL_SECONDS,
        )
        return DEFAULT_RETENTION_INTERVAL_SECONDS
    return value


def _cutoff_iso(hours: int) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


def prune_older_than(conn: Any, cutoff_iso: str) -> int:
    """Delete executions older than ``cutoff_iso`` and return the count.

    Kept for backward compat with prior tests / cron scripts. The
    background loop calls :func:`run_sweep` instead.
    """
    rows = conn.execute(
        "SELECT id FROM llm_executions WHERE started_at < ?",
        (cutoff_iso,),
    ).fetchall()
    execution_ids = [row["id"] for row in rows]
    for execution_id in execution_ids:
        conn.execute(
            "DELETE FROM llm_execution_events WHERE execution_id = ?",
            (execution_id,),
        )
    cur = conn.execute(
        "DELETE FROM llm_executions WHERE started_at < ?",
        (cutoff_iso,),
    )
    return cur.rowcount


def run_sweep(hours: int | None = None) -> int:
    """One-shot sweep. Returns the number of executions deleted.

    Exposed for tests and operators who want to drive retention
    manually. The async loop calls this on a timer.
    """
    window = hours if hours is not None else retention_hours()
    cutoff = _cutoff_iso(window)
    with observability_db.get_conn() as conn:
        deleted = prune_older_than(conn, cutoff)
    if deleted:
        LOG.info(
            "observability retention sweep removed executions=%s cutoff=%s window_hours=%s",
            deleted,
            cutoff,
            window,
        )
    return deleted


async def retention_loop(stop_event: asyncio.Event) -> None:
    """Background loop. Exits when ``stop_event`` is set.

    Spawned by :mod:`cairn.server.app` ``lifespan`` only in
    ``cairn serve`` mode. Sleeps ``OBSERVABILITY_RETENTION_INTERVAL_SECONDS``
    between sweeps and logs the outcome.
    """
    interval = retention_interval_seconds()
    LOG.info(
        "observability retention loop started interval_seconds=%s retention_hours=%s",
        interval,
        retention_hours(),
    )
    try:
        while not stop_event.is_set():
            try:
                run_sweep()
            except Exception:  # noqa: BLE001 - never let a sweep kill the loop
                LOG.exception("observability retention sweep failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue
    finally:
        LOG.info("observability retention loop stopped")
