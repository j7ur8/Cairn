"""CRUD endpoints for the system-wide proxy pool.

Proxies are project-scoped references (see ``projects.proxy_id``); this router
manages the shared proxy definitions that new projects can select from. The
worker container reads its proxy at task-launch time via
``dispatcher.protocol.client.CairnClient.get_proxy`` and injects the resolved
env vars into the container.

Auth credentials are stored in plaintext in SQLite for this round; observability
redaction covers log/observability leaks. Encryption-at-rest is a follow-up.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from cairn.server.db import get_conn
from cairn.server.models import (
    ProxyConfig,
    ProxyCreate,
    ProxySummary,
    ProxyUpdate,
)

router = APIRouter(tags=["proxies"])


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_summary(row: sqlite3.Row) -> ProxySummary:
    return ProxySummary(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        host=row["host"],
        port=row["port"],
        has_auth=bool(row["username"] or row["password"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_config(row: sqlite3.Row) -> ProxyConfig:
    return ProxyConfig(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        host=row["host"],
        port=row["port"],
        has_auth=bool(row["username"] or row["password"]),
        username=row["username"],
        password=row["password"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _new_proxy_id() -> str:
    # Short readable id; uniqueness via PRIMARY KEY constraint, not enforced
    # by counters table since proxies are operator-managed, not generated
    # in tight loops.
    return f"proxy_{uuid.uuid4().hex[:12]}"


@router.get("/proxies", response_model=list[ProxySummary])
def list_proxies():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM proxies ORDER BY created_at DESC, id"
        ).fetchall()
    return [_row_to_summary(row) for row in rows]


@router.post("/proxies", response_model=ProxyConfig, status_code=201)
def create_proxy(body: ProxyCreate):
    now = _utcnow()
    pid = _new_proxy_id()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO proxies (id, name, type, host, port, username, password, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (pid, body.name, body.type, body.host, body.port,
             body.username, body.password, now, now),
        )
        row = conn.execute("SELECT * FROM proxies WHERE id = ?", (pid,)).fetchone()
    return _row_to_config(row)


@router.get("/proxies/{proxy_id}", response_model=ProxyConfig)
def get_proxy(proxy_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"proxy not found: {proxy_id}")
    return _row_to_config(row)


@router.put("/proxies/{proxy_id}", response_model=ProxyConfig)
def update_proxy(proxy_id: str, body: ProxyUpdate):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"proxy not found: {proxy_id}")
        updates: dict[str, object] = {}
        if body.name is not None:
            updates["name"] = body.name
        if body.type is not None:
            updates["type"] = body.type
        if body.host is not None:
            updates["host"] = body.host
        if body.port is not None:
            updates["port"] = body.port
        if body.username is not None:
            updates["username"] = body.username
        if body.password is not None:
            updates["password"] = body.password
        if updates:
            updates["updated_at"] = _utcnow()
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [proxy_id]
            conn.execute(
                f"UPDATE proxies SET {set_clause} WHERE id = ?",
                values,
            )
        row = conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone()
    return _row_to_config(row)


@router.delete("/proxies/{proxy_id}", status_code=204)
def delete_proxy(proxy_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM proxies WHERE id = ?", (proxy_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"proxy not found: {proxy_id}")
        # ON DELETE SET NULL on projects.proxy_id handles the FK cascade
        # behavior at the DB layer; we just need to delete the proxy.
        conn.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
    return None
