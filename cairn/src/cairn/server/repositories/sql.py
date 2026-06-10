from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.orm import Session


Params = Mapping[str, Any] | None


def execute(session: Session, sql: str, params: Params = None) -> CursorResult[Any]:
    return session.execute(text(sql), dict(params or {}))


def fetchone(session: Session, sql: str, params: Params = None) -> RowMapping | None:
    return execute(session, sql, params).mappings().fetchone()


def fetchall(session: Session, sql: str, params: Params = None) -> list[RowMapping]:
    return list(execute(session, sql, params).mappings().fetchall())
