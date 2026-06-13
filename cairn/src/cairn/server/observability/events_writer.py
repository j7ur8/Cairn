from __future__ import annotations

from typing import Any

from cairn.server.domain.time import utcnow
from cairn.server.observability._shared import row_to_event
from cairn.server.observability.event_repository import LlmEventRepository
from cairn.server.observability.execution_repository import LlmExecutionRepository
from cairn.server.observability.models import (
    CreateEventRequest,
    LlmExecutionEvent,
    ObservabilitySettings,
)
from cairn.server.observability.redaction import redact_content, truncate_content


def append_event(
    conn: Any,
    project_id: str,
    execution_id: str,
    body: CreateEventRequest,
    settings: ObservabilitySettings,
) -> tuple[LlmExecutionEvent | None, bool]:
    events, dropped = append_events(conn, project_id, execution_id, [body], settings)
    return events[0], bool(dropped)


def append_events(
    conn: Any,
    project_id: str,
    execution_id: str,
    bodies: list[CreateEventRequest],
    settings: ObservabilitySettings,
) -> tuple[list[LlmExecutionEvent | None], int]:
    executions = LlmExecutionRepository(conn)
    events_repo = LlmEventRepository(conn)
    execution = executions.get(execution_id, project_id)
    if execution is None:
        return [None for _ in bodies], len(bodies)

    current_bytes = int(execution["bytes_written"])
    now = utcnow()
    prepared: list[dict[str, Any] | None] = []
    insert_rows: list[dict[str, Any]] = []
    total_bytes = 0
    dropped = 0
    for body in bodies:
        row, byte_count = _prepare_event_row(
            execution,
            execution_id,
            project_id,
            body,
            settings,
            current_bytes + total_bytes,
            now,
        )
        prepared.append(row)
        if row is None:
            dropped += 1
            continue
        insert_rows.append(row)
        total_bytes += byte_count

    inserted_events = [row_to_event(row) for row in events_repo.insert_event_rows(insert_rows)]
    if inserted_events:
        executions.increment_event_stats(
            execution_id=execution_id,
            last_event_at=now,
            event_count=len(inserted_events),
            byte_count=total_bytes,
        )

    inserted_iter = iter(inserted_events)
    events: list[LlmExecutionEvent | None] = []
    for row in prepared:
        events.append(None if row is None else next(inserted_iter))
    return events, dropped


def _prepare_event_row(
    execution: Any,
    execution_id: str,
    project_id: str,
    body: CreateEventRequest,
    settings: ObservabilitySettings,
    current_bytes: int,
    now: str,
) -> tuple[dict[str, Any] | None, int]:
    content, redacted = redact_content(body.content, settings.redaction_patterns)
    content, truncated = truncate_content(content, settings.max_event_bytes)
    byte_count = len(content.encode("utf-8"))
    if current_bytes + byte_count > settings.max_bytes_per_execution:
        if current_bytes >= settings.max_bytes_per_execution:
            return None, 0
        content = "Execution log byte limit reached; further output was dropped."
        truncated = True
        byte_count = len(content.encode("utf-8"))

    return (
        {
            "execution_id": execution_id,
            "project_id": project_id,
            "intent_id": execution["intent_id"],
            "task_type": execution["task_type"],
            "worker": execution["worker"],
            "phase": body.phase,
            "event_kind": body.event_kind,
            "stream": body.stream,
            "content": content,
            "truncated": 1 if truncated else 0,
            "redacted": 1 if redacted else 0,
            "created_at": now,
        },
        byte_count,
    )
