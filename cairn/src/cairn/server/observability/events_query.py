from __future__ import annotations

from typing import Any

from cairn.server.observability._shared import normalize_event_kind_filter, row_to_event
from cairn.server.observability.event_repository import LlmEventRepository
from cairn.server.observability.models import LlmExecutionEvent


def list_project_events(
    conn: Any,
    project_id: str,
    after: int,
    limit: int,
    *,
    tail: bool = False,
) -> list[LlmExecutionEvent]:
    rows = LlmEventRepository(conn).list_project_events(project_id, after, limit, tail=tail)
    return [row_to_event(row) for row in rows]


def list_execution_events(
    conn: Any,
    project_id: str,
    execution_id: str,
    after: int,
    limit: int,
    *,
    tail: bool = False,
) -> list[LlmExecutionEvent]:
    rows = LlmEventRepository(conn).list_execution_events(
        project_id,
        execution_id,
        after,
        limit,
        tail=tail,
    )
    return [row_to_event(row) for row in rows]


def list_incremental_events(
    conn: Any,
    project_id: str,
    *,
    execution_id: str | None = None,
    after: int = 0,
    limit: int = 200,
    event_kinds: list[str] | tuple[str, ...] | None = None,
) -> tuple[list[LlmExecutionEvent], int]:
    allowed_kinds = normalize_event_kind_filter(event_kinds)
    result = LlmEventRepository(conn).list_incremental_events(
        project_id,
        execution_id=execution_id,
        after=after,
        limit=limit,
        event_kinds=allowed_kinds,
    )
    events = [row_to_event(row) for row in result.rows]
    return events, result.last_sequence
