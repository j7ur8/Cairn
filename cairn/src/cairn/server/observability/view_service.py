from __future__ import annotations

from typing import Any

from cairn.server.observability._shared import normalize_event_kind_filter, row_to_event
from cairn.server.observability.event_view_repository import LlmEventViewRepository
from cairn.server.observability.models import EventViewResponse, LlmEventStats


def list_event_view(
    conn: Any,
    project_id: str,
    *,
    execution_id: str | None = None,
    after: int = 0,
    limit: int = 300,
    event_kinds: list[str] | tuple[str, ...] | None = None,
) -> EventViewResponse:
    allowed_kinds = normalize_event_kind_filter(event_kinds)
    view = LlmEventViewRepository(conn).event_view(
        project_id,
        execution_id=execution_id,
        after=after,
        limit=limit,
        event_kinds=allowed_kinds,
    )
    primary_events = [row_to_event(row) for row in view.rows]

    hidden_by_kind: dict[str, int] = {}
    if allowed_kinds is not None:
        visible = set(allowed_kinds)
        hidden_by_kind = {
            kind: count
            for kind, count in view.by_kind.items()
            if kind not in visible and count > 0
        }

    return EventViewResponse(
        primary_events=primary_events,
        stats=LlmEventStats(
            total=sum(view.by_kind.values()),
            returned=len(primary_events),
            by_kind=view.by_kind,
            hidden_by_kind=hidden_by_kind,
        ),
        last_sequence=view.last_sequence,
    )
