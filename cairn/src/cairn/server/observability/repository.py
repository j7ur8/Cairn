from __future__ import annotations

import json
from typing import Any

from cairn.server.observability.models import (
    CreateEventRequest,
    CreateExecutionRequest,
    EventViewResponse,
    FinishExecutionRequest,
    LlmEventStats,
    LlmExecution,
    LlmExecutionEvent,
    LlmUsageActivity,
    ObservabilitySettings,
)
from cairn.server.observability.redaction import redact_content, truncate_content
from cairn.server.models_pkg.projects import DEFAULT_LLM_HIDDEN_EVENT_KINDS, normalize_llm_event_kinds
from cairn.server.services import utcnow


def row_to_execution(row: Any) -> LlmExecution:
    return LlmExecution(**dict(row))


def row_to_event(row: Any) -> LlmExecutionEvent:
    return LlmExecutionEvent(**dict(row))


def create_execution(conn: Any, project_id: str, body: CreateExecutionRequest) -> LlmExecution:
    now = utcnow()
    conn.execute(
        """
        INSERT INTO llm_executions (
            id, project_id, intent_id, task_type, worker, process_state,
            started_at, ended_at, last_event_at, event_count, bytes_written,
            returncode, timed_out, error_kind, produced_fact_id, created_intent_ids
        ) VALUES (?, ?, ?, ?, ?, 'running', ?, NULL, NULL, 0, 0, NULL, 0, NULL, NULL, NULL)
        ON CONFLICT(id) DO UPDATE SET
            project_id = excluded.project_id,
            intent_id = excluded.intent_id,
            task_type = excluded.task_type,
            worker = excluded.worker,
            process_state = 'running',
            started_at = excluded.started_at,
            ended_at = NULL,
            returncode = NULL,
            timed_out = 0,
            error_kind = NULL
        """,
        (body.id, project_id, body.intent_id, body.task_type, body.worker, now),
    )
    row = conn.execute("SELECT * FROM llm_executions WHERE id = ?", (body.id,)).fetchone()
    assert row is not None
    return row_to_execution(row)


def list_executions(conn: Any, project_id: str, limit: int) -> list[LlmExecution]:
    rows = conn.execute(
        """
        SELECT
            e.id,
            e.project_id,
            e.intent_id,
            e.task_type,
            e.worker,
            e.process_state,
            e.started_at,
            e.ended_at,
            COALESCE(
                (SELECT MAX(ev.created_at) FROM llm_execution_events ev WHERE ev.execution_id = e.id),
                e.last_event_at
            ) AS last_event_at,
            GREATEST(
                e.event_count::bigint,
                (SELECT COUNT(*) FROM llm_execution_events ev WHERE ev.execution_id = e.id)
            ) AS event_count,
            GREATEST(
                e.bytes_written::bigint,
                COALESCE((SELECT SUM(LENGTH(ev.content)) FROM llm_execution_events ev WHERE ev.execution_id = e.id), 0)::bigint
            ) AS bytes_written,
            e.returncode,
            e.timed_out,
            e.error_kind,
            e.produced_fact_id,
            e.created_intent_ids
        FROM llm_executions e
        WHERE e.project_id = ?
        ORDER BY started_at DESC, id DESC
        LIMIT ?
        """,
        (project_id, limit),
    ).fetchall()
    return [row_to_execution(row) for row in rows]


def append_event(
    conn: Any,
    project_id: str,
    execution_id: str,
    body: CreateEventRequest,
    settings: ObservabilitySettings,
) -> tuple[LlmExecutionEvent | None, bool]:
    execution = conn.execute(
        "SELECT * FROM llm_executions WHERE id = ? AND project_id = ?",
        (execution_id, project_id),
    ).fetchone()
    if execution is None:
        return None, True

    current_bytes = int(execution["bytes_written"])
    content, redacted = redact_content(body.content, settings.redaction_patterns)
    content, truncated = truncate_content(content, settings.max_event_bytes)
    byte_count = len(content.encode("utf-8"))
    if current_bytes + byte_count > settings.max_bytes_per_execution:
        if current_bytes >= settings.max_bytes_per_execution:
            return None, True
        content = "Execution log byte limit reached; further output was dropped."
        truncated = True
        byte_count = len(content.encode("utf-8"))

    now = utcnow()
    cursor = conn.execute(
        """
        INSERT INTO llm_execution_events (
            execution_id, project_id, intent_id, task_type, worker, phase,
            event_kind, stream, content, truncated, redacted, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING sequence
        """,
        (
            execution_id,
            project_id,
            execution["intent_id"],
            execution["task_type"],
            execution["worker"],
            body.phase,
            body.event_kind,
            body.stream,
            content,
            1 if truncated else 0,
            1 if redacted else 0,
            now,
        ),
    )
    conn.execute(
        """
        UPDATE llm_executions
        SET last_event_at = ?,
            event_count = event_count + 1,
            bytes_written = bytes_written + ?
        WHERE id = ?
        """,
        (now, byte_count, execution_id),
    )
    row = conn.execute(
        "SELECT * FROM llm_execution_events WHERE sequence = ?",
        (cursor.fetchone()["sequence"],),
    ).fetchone()
    assert row is not None
    return row_to_event(row), False


def append_events(
    conn: Any,
    project_id: str,
    execution_id: str,
    bodies: list[CreateEventRequest],
    settings: ObservabilitySettings,
) -> tuple[list[LlmExecutionEvent | None], int]:
    events: list[LlmExecutionEvent | None] = []
    dropped = 0
    for body in bodies:
        event, was_dropped = append_event(conn, project_id, execution_id, body, settings)
        events.append(event)
        if was_dropped:
            dropped += 1
    return events, dropped


def finish_execution(
    conn: Any,
    project_id: str,
    execution_id: str,
    body: FinishExecutionRequest,
) -> LlmExecution | None:
    now = utcnow()
    created_intent_ids = None
    if body.created_intent_ids is not None:
        created_intent_ids = json.dumps(body.created_intent_ids, ensure_ascii=False)
    conn.execute(
        """
        UPDATE llm_executions
        SET process_state = ?,
            ended_at = ?,
            returncode = ?,
            timed_out = ?,
            error_kind = ?,
            produced_fact_id = COALESCE(?, produced_fact_id),
            created_intent_ids = COALESCE(?, created_intent_ids)
        WHERE id = ? AND project_id = ?
        """,
        (
            body.process_state,
            now,
            body.returncode,
            1 if body.timed_out else 0,
            body.error_kind,
            body.produced_fact_id,
            created_intent_ids,
            execution_id,
            project_id,
        ),
    )
    row = conn.execute(
        "SELECT * FROM llm_executions WHERE id = ? AND project_id = ?",
        (execution_id, project_id),
    ).fetchone()
    if row is not None:
        _ensure_process_end_event(conn, row, body, now)
    return row_to_execution(row) if row is not None else None


def _ensure_process_end_event(
    conn: Any,
    execution: Any,
    body: FinishExecutionRequest,
    now: str,
) -> None:
    existing = conn.execute(
        """
        SELECT 1 FROM llm_execution_events
        WHERE execution_id = ? AND event_kind = 'process_end'
        LIMIT 1
        """,
        (execution["id"],),
    ).fetchone()
    if existing is not None:
        return
    content = (
        f"process_state={body.process_state} returncode={body.returncode} "
        f"timed_out={body.timed_out} error_kind={body.error_kind or ''}"
    )
    byte_count = len(content.encode("utf-8"))
    conn.execute(
        """
        INSERT INTO llm_execution_events (
            execution_id, project_id, intent_id, task_type, worker, phase,
            event_kind, stream, content, truncated, redacted, created_at
        ) VALUES (?, ?, ?, ?, ?, 'finish', 'process_end', 'system', ?, 0, 0, ?)
        """,
        (
            execution["id"],
            execution["project_id"],
            execution["intent_id"],
            execution["task_type"],
            execution["worker"],
            content,
            now,
        ),
    )
    conn.execute(
        """
        UPDATE llm_executions
        SET last_event_at = ?,
            event_count = event_count + 1,
            bytes_written = bytes_written + ?
        WHERE id = ?
        """,
        (now, byte_count, execution["id"]),
    )


def list_project_events(
    conn: Any,
    project_id: str,
    after: int,
    limit: int,
    *,
    tail: bool = False,
) -> list[LlmExecutionEvent]:
    if tail:
        rows = conn.execute(
            """
            SELECT * FROM llm_execution_events
            WHERE project_id = ?
            ORDER BY sequence DESC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
        rows = list(reversed(rows))
        return [row_to_event(row) for row in rows]
    rows = conn.execute(
        """
        SELECT * FROM llm_execution_events
        WHERE project_id = ? AND sequence > ?
        ORDER BY sequence ASC
        LIMIT ?
        """,
        (project_id, after, limit),
    ).fetchall()
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
    if tail:
        rows = conn.execute(
            """
            SELECT * FROM llm_execution_events
            WHERE project_id = ? AND execution_id = ?
            ORDER BY sequence DESC
            LIMIT ?
            """,
            (project_id, execution_id, limit),
        ).fetchall()
        rows = list(reversed(rows))
        return [row_to_event(row) for row in rows]
    rows = conn.execute(
        """
        SELECT * FROM llm_execution_events
        WHERE project_id = ? AND execution_id = ? AND sequence > ?
        ORDER BY sequence ASC
        LIMIT ?
        """,
        (project_id, execution_id, after, limit),
    ).fetchall()
    return [row_to_event(row) for row in rows]


def list_event_view(
    conn: Any,
    project_id: str,
    *,
    execution_id: str | None = None,
    after: int = 0,
    limit: int = 300,
    include_low_signal: bool = False,
    hidden_event_kinds: list[str] | tuple[str, ...] | None = None,
) -> EventViewResponse:
    where = ["project_id = ?"]
    params: list[object] = [project_id]
    if execution_id:
        where.append("execution_id = ?")
        params.append(execution_id)
    if after > 0:
        where.append("sequence > ?")
        params.append(after)
    where_sql = " AND ".join(where)

    max_row = conn.execute(
        f"SELECT MAX(sequence) AS last_sequence FROM llm_execution_events WHERE {where_sql}",
        params,
    ).fetchone()
    last_sequence = int(max_row["last_sequence"] or after) if max_row is not None else after

    stat_rows = conn.execute(
        f"""
        SELECT event_kind, COUNT(*) AS count
        FROM llm_execution_events
        WHERE {where_sql}
        GROUP BY event_kind
        """,
        params,
    ).fetchall()
    by_kind = {str(row["event_kind"]): int(row["count"]) for row in stat_rows}

    event_where = list(where)
    event_params = list(params)
    hidden_kinds = normalize_llm_event_kinds(
        hidden_event_kinds if hidden_event_kinds is not None else list(DEFAULT_LLM_HIDDEN_EVENT_KINDS)
    )
    if not include_low_signal:
        if hidden_kinds:
            placeholders = ", ".join("?" for _ in hidden_kinds)
            event_where.append(f"event_kind NOT IN ({placeholders})")
            event_params.extend(hidden_kinds)
    rows = conn.execute(
        f"""
        SELECT * FROM llm_execution_events
        WHERE {" AND ".join(event_where)}
        ORDER BY sequence DESC
        LIMIT ?
        """,
        [*event_params, limit],
    ).fetchall()
    primary_events = [row_to_event(row) for row in rows]

    hidden_by_kind: dict[str, int] = {}
    if not include_low_signal:
        hidden_by_kind = {kind: by_kind.get(kind, 0) for kind in hidden_kinds if by_kind.get(kind, 0) > 0}

    activity = _latest_usage_activity(conn, where_sql, params)
    return EventViewResponse(
        primary_events=primary_events,
        activity=activity,
        stats=LlmEventStats(
            total=sum(by_kind.values()),
            returned=len(primary_events),
            by_kind=by_kind,
            hidden_by_kind=hidden_by_kind,
        ),
        last_sequence=last_sequence,
    )


def _latest_usage_activity(
    conn: Any,
    where_sql: str,
    params: list[object],
) -> LlmUsageActivity | None:
    usage_count_row = conn.execute(
        f"SELECT COUNT(*) AS count FROM llm_execution_events WHERE {where_sql} AND event_kind = 'usage'",
        params,
    ).fetchone()
    usage_count = int(usage_count_row["count"] or 0) if usage_count_row is not None else 0
    if usage_count <= 0:
        return None
    row = conn.execute(
        f"""
        SELECT * FROM llm_execution_events
        WHERE {where_sql} AND event_kind = 'usage'
        ORDER BY sequence DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    if row is None:
        return None
    payload = _parse_json_object(str(row["content"] or ""))
    subtype = payload.get("subtype") if isinstance(payload.get("subtype"), str) else None
    tokens = _optional_int(
        payload.get("estimated_tokens")
        if payload.get("estimated_tokens") is not None
        else payload.get("thinking_tokens")
        if payload.get("thinking_tokens") is not None
        else payload.get("output_tokens")
        if payload.get("output_tokens") is not None
        else payload.get("input_tokens")
    )
    return LlmUsageActivity(
        latest_usage_sequence=int(row["sequence"]),
        latest_usage_at=str(row["created_at"]),
        subtype=subtype,
        tokens=tokens,
        delta=_optional_int(payload.get("estimated_tokens_delta")),
        hidden_usage_count=usage_count,
    )


def _parse_json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def delete_project_observability(conn: Any, project_id: str) -> None:
    conn.execute("DELETE FROM llm_execution_events WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM llm_executions WHERE project_id = ?", (project_id,))
