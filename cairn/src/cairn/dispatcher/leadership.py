"""SQLite advisory leader election for dispatcher replicas.

Cairn's dispatcher is stateful: it starts worker containers and
reports task state back to the server. Running two dispatchers against
one server without coordination can launch duplicate containers. This
module provides a lightweight at-most-one active dispatcher lock using
``cairn.db`` itself.

It is intentionally conservative:

* one lock row per name (default ``dispatcher``)
* holder is a unique process id string
* a stale row is stealable when ``heartbeat_at`` is older than TTL
* callers must heartbeat every few seconds while active

This is not a replacement for a real distributed lock in a multi-host
Postgres/K8s deployment, but it removes the accidental duplicate
local dispatcher problem without requiring Redis/etcd.
"""
from __future__ import annotations

import os
import socket
import time
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator

from cairn.server import db as server_db
from cairn.server.db import get_conn, with_immediate_tx
from cairn.server.sqlite_diagnostics import is_transient_database_error


class LeadershipLost(RuntimeError):
    """Raised when the dispatcher loses its leader lock mid-tick.

    Callers (typically the scheduler loop) catch this, drain any
    leadership-scoped work, and re-acquire. The loop treats it as a
    controlled shutdown signal for the current dispatching pass.
    """


DEFAULT_LOCK_NAME = "dispatcher"
DEFAULT_TTL_SECONDS = 15.0
DEFAULT_HEARTBEAT_SECONDS = 3.0

LOG = logging.getLogger(__name__)
SQLITE_RETRY_ATTEMPTS = 3
SQLITE_RETRY_DELAY_SECONDS = 0.25


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _holder_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"


def _parse_iso(value: str) -> float:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


@dataclass(slots=True)
class DispatcherLeader:
    """Holds and renews a single dispatcher leader lock."""

    name: str = DEFAULT_LOCK_NAME
    ttl_seconds: float = DEFAULT_TTL_SECONDS
    holder: str = field(default_factory=_holder_id)
    _last_heartbeat_at: float = 0.0
    _is_leader: bool = False

    @property
    def is_leader(self) -> bool:
        return self._is_leader and not self.is_expired()

    @property
    def last_heartbeat_age(self) -> float | None:
        if not self._last_heartbeat_at:
            return None
        return max(0.0, time.time() - self._last_heartbeat_at)

    def acquire(self) -> bool:
        """Try to become leader.

        Returns ``True`` if this holder now owns the lock; ``False``
        if another non-expired holder owns it.
        """
        return self._with_sqlite_retry("acquire", self._acquire_once)

    def _acquire_once(self) -> bool:
        now = _utcnow()
        with with_immediate_tx() as conn:
            row = conn.execute(
                "SELECT holder, heartbeat_at FROM dispatcher_locks WHERE name = ?",
                (self.name,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO dispatcher_locks (name, holder, acquired_at, heartbeat_at) VALUES (?, ?, ?, ?)",
                    (self.name, self.holder, now, now),
                )
                self._mark_leader()
                return True
            if row["holder"] == self.holder:
                conn.execute(
                    "UPDATE dispatcher_locks SET heartbeat_at = ? WHERE name = ? AND holder = ?",
                    (now, self.name, self.holder),
                )
                self._mark_leader()
                return True
            heartbeat_at = _parse_iso(row["heartbeat_at"])
            if time.time() - heartbeat_at > self.ttl_seconds:
                conn.execute(
                    "UPDATE dispatcher_locks SET holder = ?, acquired_at = ?, heartbeat_at = ? WHERE name = ?",
                    (self.holder, now, now, self.name),
                )
                self._mark_leader()
                return True
        self._is_leader = False
        return False

    def heartbeat(self) -> bool:
        """Renew the lock if this holder owns it."""
        return self._with_sqlite_retry("heartbeat", self._heartbeat_once)

    def _heartbeat_once(self) -> bool:
        now = _utcnow()
        with with_immediate_tx() as conn:
            cur = conn.execute(
                "UPDATE dispatcher_locks SET heartbeat_at = ? WHERE name = ? AND holder = ?",
                (now, self.name, self.holder),
            )
            if cur.rowcount == 1:
                self._mark_leader()
                return True
        self._is_leader = False
        return False

    def release(self) -> None:
        """Best-effort unlock on graceful shutdown."""
        self._with_sqlite_retry("release", self._release_once)

    def _release_once(self) -> bool:
        with with_immediate_tx() as conn:
            conn.execute(
                "DELETE FROM dispatcher_locks WHERE name = ? AND holder = ?",
                (self.name, self.holder),
            )
        self._is_leader = False
        return True

    def current_holder(self) -> str | None:
        return self._with_sqlite_retry("current_holder", self._current_holder_once)

    def _current_holder_once(self) -> str | None:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT holder FROM dispatcher_locks WHERE name = ?",
                (self.name,),
            ).fetchone()
        return row["holder"] if row else None

    def is_expired(self) -> bool:
        return self._with_sqlite_retry("is_expired", self._is_expired_once)

    def _is_expired_once(self) -> bool:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT heartbeat_at FROM dispatcher_locks WHERE name = ? AND holder = ?",
                (self.name, self.holder),
            ).fetchone()
        if row is None:
            return True
        return time.time() - _parse_iso(row["heartbeat_at"]) > self.ttl_seconds

    def _mark_leader(self) -> None:
        self._is_leader = True
        self._last_heartbeat_at = time.time()

    def check_health(self) -> None:
        """Raise :class:`LeadershipLost` if we no longer own the lock.

        The loop calls this between major sub-steps of a tick (e.g. after
        ``list_projects``, after ``_dispatch_available``) so a stolen
        lock surfaces as an explicit exception that unwinds the tick
        cleanly, rather than silently continuing to dispatch as a
        follower. ``heartbeat_at`` drift is the primary signal.
        """
        row = self._with_sqlite_retry("check_health", self._check_health_row)
        if row is None:
            self._is_leader = False
            raise LeadershipLost(
                f"dispatcher lock {self.name!r} no longer held by {self.holder!r}"
            )
        if time.time() - _parse_iso(row["heartbeat_at"]) > self.ttl_seconds:
            self._is_leader = False
            raise LeadershipLost(
                f"dispatcher lock {self.name!r} heartbeat stale for holder {self.holder!r}"
            )

    def _check_health_row(self):
        with get_conn() as conn:
            return conn.execute(
                "SELECT heartbeat_at FROM dispatcher_locks WHERE name = ? AND holder = ?",
                (self.name, self.holder),
            ).fetchone()

    def _with_sqlite_retry(self, operation: str, func):
        last_exc: sqlite3.DatabaseError | None = None
        for attempt in range(1, SQLITE_RETRY_ATTEMPTS + 1):
            try:
                return func()
            except sqlite3.DatabaseError as exc:
                last_exc = exc
                if not is_transient_database_error(exc) or attempt >= SQLITE_RETRY_ATTEMPTS:
                    break
                detail = server_db.diagnostic_error(exc)
                LOG.warning(
                    "dispatcher sqlite transient error operation=%s attempt=%s/%s detail=%s",
                    operation,
                    attempt,
                    SQLITE_RETRY_ATTEMPTS,
                    detail,
                )
                server_db.close_thread_conn()
                time.sleep(SQLITE_RETRY_DELAY_SECONDS * attempt)
        assert last_exc is not None
        detail = server_db.diagnostic_error(last_exc)
        raise RuntimeError(
            f"dispatcher sqlite {operation} failed after {SQLITE_RETRY_ATTEMPTS} attempts: {detail}. "
            "Run `cairn db diagnose` and do not delete -wal/-shm files while Cairn is running."
        ) from last_exc

    @contextmanager
    def acquired(self, *, retry_interval: float = 1.0) -> Iterator[None]:
        """Context manager that blocks until the lock is held.

        Behaviour:

        * Loops on ``acquire()`` until success, sleeping
          ``retry_interval`` seconds between attempts. Lets the
          follower half of the dispatcher stay warm and observe the
          current leader via :meth:`current_holder` without busy
          spinning.
        * Yields ``None`` once leader. The caller is expected to
          ``heartbeat()`` at its own cadence; we do *not* auto
          heartbeat inside the context to keep policy in one place
          (the loop).
        * On exit, releases the lock if and only if we still own it,
          to avoid the case where a different holder has taken over
          while we were sleeping through an exception handler.
        * If :meth:`check_health` ever raises :class:`LeadershipLost`
          inside the ``with`` block, the context swallows the
          release attempt and re-raises so the loop can step down
          cleanly.

        The context is *not* safe to re-enter from another thread on
        the same instance; the lock holder identity is per-process.
        """
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
            # Caller already knows; do not double-release.
            raise
        finally:
            try:
                if self.is_leader:
                    self.release()
            except Exception:  # noqa: BLE001 - release is best-effort
                LOG.exception("dispatcher leader release failed")
