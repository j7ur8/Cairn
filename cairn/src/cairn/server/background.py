from __future__ import annotations

import asyncio
import logging

from cairn.server import db
from cairn.server.observability.retention import retention_loop
from cairn.server.repositories.leases import LeaseRepository
from cairn.shared.config import SystemConfig

LOG = logging.getLogger(__name__)


async def lease_cleanup_loop(stop: asyncio.Event, *, interval_seconds: float = 2.0) -> None:
    while not stop.is_set():
        try:
            with db.session_scope() as conn:
                leases = LeaseRepository(conn)
                leases.expire_workers()
                leases.expire_reason_leases()
        except Exception as exc:  # noqa: BLE001
            LOG.warning("lease cleanup failed error=%s", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


class BackgroundTasks:
    def __init__(self, runtime: SystemConfig) -> None:
        self.runtime = runtime
        self.retention_stop = asyncio.Event()
        self.lease_cleanup_stop = asyncio.Event()
        self.retention_task: asyncio.Task | None = None
        self.lease_cleanup_task: asyncio.Task | None = None

    def start(self) -> None:
        if self.runtime.server.retention_loop_enabled:
            self.retention_task = asyncio.create_task(
                retention_loop(
                    self.retention_stop,
                    interval_seconds=self.runtime.server.retention_interval_seconds,
                ),
                name="cairn-retention",
            )
        self.lease_cleanup_task = asyncio.create_task(
            lease_cleanup_loop(self.lease_cleanup_stop),
            name="cairn-lease-cleanup",
        )

    async def stop(self) -> None:
        if self.lease_cleanup_task is not None:
            self.lease_cleanup_stop.set()
            try:
                await self.lease_cleanup_task
            except Exception:  # noqa: BLE001
                LOG.exception("lease cleanup task crashed")
        if self.retention_task is not None:
            self.retention_stop.set()
            try:
                await self.retention_task
            except Exception:  # noqa: BLE001
                LOG.exception("retention task crashed")
