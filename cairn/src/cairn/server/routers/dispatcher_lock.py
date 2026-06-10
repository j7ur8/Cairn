from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, Field

from cairn.server import db
from cairn.server.repositories import sql

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
    with db.session_scope() as conn:
        row = sql.fetchone(
            conn,
            "SELECT holder, heartbeat_at FROM dispatcher_locks WHERE name = :name",
            {"name": body.name},
        )
        if row is None:
            sql.execute(
                conn,
                """
                INSERT INTO dispatcher_locks (name, holder, acquired_at, heartbeat_at)
                VALUES (:name, :holder, :acquired_at, :heartbeat_at)
                """,
                {"name": body.name, "holder": body.holder, "acquired_at": now, "heartbeat_at": now},
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
            sql.execute(
                conn,
                """
                UPDATE dispatcher_locks
                SET heartbeat_at = :heartbeat_at
                WHERE name = :name AND holder = :holder
                """,
                {"heartbeat_at": now, "name": body.name, "holder": body.holder},
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
            sql.execute(
                conn,
                """
                UPDATE dispatcher_locks
                SET holder = :holder, acquired_at = :acquired_at, heartbeat_at = :heartbeat_at
                WHERE name = :name
                """,
                {"holder": body.holder, "acquired_at": now, "heartbeat_at": now, "name": body.name},
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
    with db.session_scope() as conn:
        cur = sql.execute(
            conn,
            """
            UPDATE dispatcher_locks
            SET heartbeat_at = :heartbeat_at
            WHERE name = :name AND holder = :holder
            """,
            {"heartbeat_at": now, "name": body.name, "holder": body.holder},
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
    with db.session_scope() as conn:
        cur = sql.execute(
            conn,
            "DELETE FROM dispatcher_locks WHERE name = :name AND holder = :holder",
            {"name": body.name, "holder": body.holder},
        )
    return DispatcherLockResponse(
        name=body.name,
        holder=body.holder if cur.rowcount == 1 else None,
        released=cur.rowcount == 1,
    )


@router.get("/current", response_model=DispatcherLockResponse)
def current(name: str = "dispatcher") -> DispatcherLockResponse:
    with db.session_scope() as conn:
        row = sql.fetchone(
            conn,
            "SELECT holder, heartbeat_at FROM dispatcher_locks WHERE name = :name",
            {"name": name},
        )
    if row is None:
        return DispatcherLockResponse(name=name)
    return DispatcherLockResponse(
        name=name,
        holder=row["holder"],
        held=True,
        heartbeat_at=row["heartbeat_at"],
    )
