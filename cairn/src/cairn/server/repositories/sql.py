from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

Params = Mapping[str, Any] | None


def execute(session: Session, sql: str, params: Params = None) -> Any:
    return session.execute(text(sql), dict(params or {}))


def fetchone(session: Session, sql: str, params: Params = None) -> Any | None:
    return execute(session, sql, params).mappings().fetchone()


def fetchall(session: Session, sql: str, params: Params = None) -> list[Any]:
    return list(execute(session, sql, params).mappings().fetchall())
