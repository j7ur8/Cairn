from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, Field

from cairn.server.db import get_conn, with_immediate_tx

router = APIRouter(prefix="/dispatcher-lock", tags=["dispatcher-lock"])


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return 0.0


class DispatcherLockRequest(BaseModel):
    name: str = Field(default="dispatcher", min_length=1)
    holder: str = Field(min_length=1)


class DispatcherLockAcquireRequest(DispatcherLockRequest):
    ttl_seconds: float = Field(default=15.0, gt=0, le=3600)


class DispatcherLockResponse(BaseModel):
    name: str
    holder: str | None = None
    acquired: bool = False
    held: bool = False
    released: bool = False
    heartbeat_at: str | None = None


@router.post("/acquire", response_model=DispatcherLockResponse)
def acquire(body: DispatcherLockAcquireRequest) -> DispatcherLockResponse:
    now = _utcnow()
    with with_immediate_tx() as conn:
        row = conn.execute(
            "SELECT holder, heartbeat_at FROM dispatcher_locks WHERE name = ?",
            (body.name,),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO dispatcher_locks (name, holder, acquired_at, heartbeat_at) VALUES (?, ?, ?, ?)",
                (body.name, body.holder, now, now),
            )
            return DispatcherLockResponse(
                name=body.name,
                holder=body.holder,
                acquired=True,
                held=True,
                heartbeat_at=now,
            )
        current_holder = row["holder"]
        if current_holder == body.holder:
            conn.execute(
                "UPDATE dispatcher_locks SET heartbeat_at = ? WHERE name = ? AND holder = ?",
                (now, body.name, body.holder),
            )
            return DispatcherLockResponse(
                name=body.name,
                holder=body.holder,
                acquired=True,
                held=True,
                heartbeat_at=now,
            )
        heartbeat_at = _parse_iso(row["heartbeat_at"])
        if time.time() - heartbeat_at > body.ttl_seconds:
            conn.execute(
                "UPDATE dispatcher_locks SET holder = ?, acquired_at = ?, heartbeat_at = ? WHERE name = ?",
                (body.holder, now, now, body.name),
            )
            return DispatcherLockResponse(
                name=body.name,
                holder=body.holder,
                acquired=True,
                held=True,
                heartbeat_at=now,
            )
        return DispatcherLockResponse(
            name=body.name,
            holder=current_holder,
            acquired=False,
            held=False,
            heartbeat_at=row["heartbeat_at"],
        )


@router.post("/heartbeat", response_model=DispatcherLockResponse)
def heartbeat(body: DispatcherLockRequest) -> DispatcherLockResponse:
    now = _utcnow()
    with with_immediate_tx() as conn:
        cur = conn.execute(
            "UPDATE dispatcher_locks SET heartbeat_at = ? WHERE name = ? AND holder = ?",
            (now, body.name, body.holder),
        )
    held = cur.rowcount == 1
    return DispatcherLockResponse(
        name=body.name,
        holder=body.holder if held else None,
        held=held,
        heartbeat_at=now if held else None,
    )


@router.post("/release", response_model=DispatcherLockResponse)
def release(body: DispatcherLockRequest) -> DispatcherLockResponse:
    with with_immediate_tx() as conn:
        cur = conn.execute(
            "DELETE FROM dispatcher_locks WHERE name = ? AND holder = ?",
            (body.name, body.holder),
        )
    return DispatcherLockResponse(
        name=body.name,
        holder=body.holder if cur.rowcount == 1 else None,
        released=cur.rowcount == 1,
    )


@router.get("/current", response_model=DispatcherLockResponse)
def current(name: str = "dispatcher") -> DispatcherLockResponse:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT holder, heartbeat_at FROM dispatcher_locks WHERE name = ?",
            (name,),
        ).fetchone()
    if row is None:
        return DispatcherLockResponse(name=name)
    return DispatcherLockResponse(
        name=name,
        holder=row["holder"],
        held=True,
        heartbeat_at=row["heartbeat_at"],
    )
