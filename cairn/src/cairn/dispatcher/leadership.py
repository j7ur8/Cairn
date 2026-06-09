"""Server-backed advisory leader election for dispatcher replicas.

Cairn's dispatcher is stateful: it starts worker containers and reports task
state back to the server. Running two dispatchers against one server without
coordination can launch duplicate containers. This module provides a
lightweight at-most-one active dispatcher lock.

Dispatcher replicas acquire, renew, inspect, and release the lock through HTTP
endpoints, keeping database concurrency centralized in the server.
"""
from __future__ import annotations

import logging
import os
import socket
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from cairn.dispatcher.protocol.client import CairnClient


class LeadershipLost(RuntimeError):
    """Raised when the dispatcher loses its leader lock mid-tick."""


DEFAULT_LOCK_NAME = "dispatcher"
DEFAULT_TTL_SECONDS = 15.0
DEFAULT_HEARTBEAT_SECONDS = 3.0

LOG = logging.getLogger(__name__)


def _holder_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"


@dataclass(slots=True)
class DispatcherLeader:
    """Holds and renews a single dispatcher leader lock through the server API."""

    client: CairnClient
    name: str = DEFAULT_LOCK_NAME
    ttl_seconds: float = DEFAULT_TTL_SECONDS
    holder: str = field(default_factory=_holder_id)
    _last_heartbeat_at: float = 0.0
    _is_leader: bool = False

    @property
    def is_leader(self) -> bool:
        if not self._is_leader:
            return False
        age = self.last_heartbeat_age
        return age is not None and age <= self.ttl_seconds

    @property
    def last_heartbeat_age(self) -> float | None:
        if not self._last_heartbeat_at:
            return None
        return max(0.0, time.time() - self._last_heartbeat_at)

    def acquire(self) -> bool:
        """Try to become leader."""
        result = self.client.dispatcher_lock_acquire(self.name, self.holder, self.ttl_seconds)
        if result.ok and isinstance(result.data, dict) and result.data.get("acquired") is True:
            self._mark_leader()
            return True
        self._is_leader = False
        return False

    def heartbeat(self) -> bool:
        """Renew the lock if this holder owns it."""
        result = self.client.dispatcher_lock_heartbeat(self.name, self.holder)
        if result.ok and isinstance(result.data, dict) and result.data.get("held") is True:
            self._mark_leader()
            return True
        self._is_leader = False
        return False

    def release(self) -> None:
        """Best-effort unlock on graceful shutdown."""
        self.client.dispatcher_lock_release(self.name, self.holder)
        self._is_leader = False

    def current_holder(self) -> str | None:
        result = self.client.dispatcher_lock_current(self.name)
        if result.ok and isinstance(result.data, dict):
            holder = result.data.get("holder")
            return holder if isinstance(holder, str) and holder else None
        return None

    def is_expired(self) -> bool:
        age = self.last_heartbeat_age
        if age is None:
            return True
        return age > self.ttl_seconds

    def _mark_leader(self) -> None:
        self._is_leader = True
        self._last_heartbeat_at = time.time()

    def check_health(self) -> None:
        """Raise :class:`LeadershipLost` if we no longer own the lock."""
        result = self.client.dispatcher_lock_current(self.name)
        if not result.ok or not isinstance(result.data, dict):
            self._is_leader = False
            raise LeadershipLost(
                f"dispatcher lock {self.name!r} health check failed status={result.status_code}"
            )
        if result.data.get("holder") != self.holder:
            self._is_leader = False
            raise LeadershipLost(
                f"dispatcher lock {self.name!r} no longer held by {self.holder!r}"
            )
        if self.is_expired():
            self._is_leader = False
            raise LeadershipLost(
                f"dispatcher lock {self.name!r} heartbeat stale for holder {self.holder!r}"
            )

    @contextmanager
    def acquired(self, *, retry_interval: float = 1.0) -> Iterator[None]:
        """Block until the lock is held, then release it on graceful exit."""
        while not self.acquire():
            LOG.info(
                "dispatcher follower waiting lock=%s holder=%s retry_in=%ss",
                self.name,
                self.current_holder(),
                retry_interval,
            )
            time.sleep(retry_interval)
        try:
            yield
        except LeadershipLost:
            raise
        finally:
            try:
                if self._is_leader:
                    self.release()
            except Exception:  # noqa: BLE001 - release is best-effort
                LOG.exception("dispatcher leader release failed")
