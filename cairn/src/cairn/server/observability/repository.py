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
from cairn.server.repositories import sql
from cairn.server.services import utcnow


def row_to_execution(row: Any) -> LlmExecution:
    return LlmExecution(**dict(row))


def row_to_event(row: Any) -> LlmExecutionEvent:
    return LlmExecutionEvent(**dict(row))


def create_execution(conn: Any, project_id: str, body: CreateExecutionRequest) -> LlmExecution:
    now = utcnow()
    sql.execute(
        conn,
        """
        INSERT INTO llm_executions (
            id, project_id, intent_id, task_type, worker, process_state,
            started_at, ended_at, last_event_at, event_count, bytes_written,
            returncode, timed_out, error_kind, produced_fact_id, created_intent_ids
        ) VALUES (
            :id, :project_id, :intent_id, :task_type, :worker, 'running',
            :started_at, NULL, NULL, 0, 0, NULL, 0, NULL, NULL, NULL
        )
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
        {
            "id": body.id,
            "project_id": project_id,
            "intent_id": body.intent_id,
            "task_type": body.task_type,
            "worker": body.worker,
            "started_at": now,
        },
    )
    row = sql.fetchone(conn, "SELECT * FROM llm_executions WHERE id = :id", {"id": body.id})
    assert row is not None
    return row_to_execution(row)


def list_executions(conn: Any, project_id: str, limit: int) -> list[LlmExecution]:
    rows = sql.fetchall(
        conn,
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
        WHERE e.project_id = :project_id
        ORDER BY started_at DESC, id DESC
        LIMIT :limit
        """,
        {"project_id": project_id, "limit": limit},
    )
    return [row_to_execution(row) for row in rows]


def append_event(
    conn: Any,
    project_id: str,
    execution_id: str,
    body: CreateEventRequest,
    settings: ObservabilitySettings,
) -> tuple[LlmExecutionEvent | None, bool]:
    execution = sql.fetchone(
        conn,
        "SELECT * FROM llm_executions WHERE id = :execution_id AND project_id = :project_id",
        {"execution_id": execution_id, "project_id": project_id},
    )
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
    cursor = sql.execute(
        conn,
        """
        INSERT INTO llm_execution_events (
            execution_id, project_id, intent_id, task_type, worker, phase,
            event_kind, stream, content, truncated, redacted, created_at
        ) VALUES (
            :execution_id, :project_id, :intent_id, :task_type, :worker, :phase,
            :event_kind, :stream, :content, :truncated, :redacted, :created_at
        )
        RETURNING sequence
        """,
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
    )
    sql.execute(
        conn,
        """
        UPDATE llm_executions
        SET last_event_at = :last_event_at,
            event_count = event_count + 1,
            bytes_written = bytes_written + :byte_count
        WHERE id = :execution_id
        """,
        {"last_event_at": now, "byte_count": byte_count, "execution_id": execution_id},
    )
    inserted = cursor.mappings().fetchone()
    row = sql.fetchone(
        conn,
        "SELECT * FROM llm_execution_events WHERE sequence = :sequence",
        {"sequence": inserted["sequence"]},
    )
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
    sql.execute(
        conn,
        """
        UPDATE llm_executions
        SET process_state = :process_state,
            ended_at = :ended_at,
            returncode = :returncode,
            timed_out = :timed_out,
            error_kind = :error_kind,
            produced_fact_id = COALESCE(:produced_fact_id, produced_fact_id),
            created_intent_ids = COALESCE(:created_intent_ids, created_intent_ids)
        WHERE id = :execution_id AND project_id = :project_id
        """,
        {
            "process_state": body.process_state,
            "ended_at": now,
            "returncode": body.returncode,
            "timed_out": 1 if body.timed_out else 0,
            "error_kind": body.error_kind,
            "produced_fact_id": body.produced_fact_id,
            "created_intent_ids": created_intent_ids,
            "execution_id": execution_id,
            "project_id": project_id,
        },
    )
    row = sql.fetchone(
        conn,
        "SELECT * FROM llm_executions WHERE id = :execution_id AND project_id = :project_id",
        {"execution_id": execution_id, "project_id": project_id},
    )
    if row is not None:
        _ensure_process_end_event(conn, row, body, now)
    return row_to_execution(row) if row is not None else None


def _ensure_process_end_event(
    conn: Any,
    execution: Any,
    body: FinishExecutionRequest,
    now: str,
) -> None:
    existing = sql.fetchone(
        conn,
        """
        SELECT 1 FROM llm_execution_events
        WHERE execution_id = :execution_id AND event_kind = 'process_end'
        LIMIT 1
        """,
        {"execution_id": execution["id"]},
    )
    if existing is not None:
        return
    content = (
        f"process_state={body.process_state} returncode={body.returncode} "
        f"timed_out={body.timed_out} error_kind={body.error_kind or ''}"
    )
    byte_count = len(content.encode("utf-8"))
    sql.execute(
        conn,
        """
        INSERT INTO llm_execution_events (
            execution_id, project_id, intent_id, task_type, worker, phase,
            event_kind, stream, content, truncated, redacted, created_at
        ) VALUES (
            :execution_id, :project_id, :intent_id, :task_type, :worker,
            'finish', 'process_end', 'system', :content, 0, 0, :created_at
        )
        """,
        {
            "execution_id": execution["id"],
            "project_id": execution["project_id"],
            "intent_id": execution["intent_id"],
            "task_type": execution["task_type"],
            "worker": execution["worker"],
            "content": content,
            "created_at": now,
        },
    )
    sql.execute(
        conn,
        """
        UPDATE llm_executions
        SET last_event_at = :last_event_at,
            event_count = event_count + 1,
            bytes_written = bytes_written + :byte_count
        WHERE id = :execution_id
        """,
        {"last_event_at": now, "byte_count": byte_count, "execution_id": execution["id"]},
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
        rows = sql.fetchall(
            conn,
            """
            SELECT * FROM llm_execution_events
            WHERE project_id = :project_id
            ORDER BY sequence DESC
            LIMIT :limit
            """,
            {"project_id": project_id, "limit": limit},
        )
        rows = list(reversed(rows))
        return [row_to_event(row) for row in rows]
    rows = sql.fetchall(
        conn,
        """
        SELECT * FROM llm_execution_events
        WHERE project_id = :project_id AND sequence > :after
        ORDER BY sequence ASC
        LIMIT :limit
        """,
        {"project_id": project_id, "after": after, "limit": limit},
    )
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
        rows = sql.fetchall(
            conn,
            """
            SELECT * FROM llm_execution_events
            WHERE project_id = :project_id AND execution_id = :execution_id
            ORDER BY sequence DESC
            LIMIT :limit
            """,
            {"project_id": project_id, "execution_id": execution_id, "limit": limit},
        )
        rows = list(reversed(rows))
        return [row_to_event(row) for row in rows]
    rows = sql.fetchall(
        conn,
        """
        SELECT * FROM llm_execution_events
        WHERE project_id = :project_id AND execution_id = :execution_id AND sequence > :after
        ORDER BY sequence ASC
        LIMIT :limit
        """,
        {"project_id": project_id, "execution_id": execution_id, "after": after, "limit": limit},
    )
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
    where = ["project_id = :project_id"]
    params: dict[str, object] = {"project_id": project_id}
    if execution_id:
        where.append("execution_id = :execution_id")
        params["execution_id"] = execution_id
    if after > 0:
        where.append("sequence > :after")
        params["after"] = after
    where_sql = " AND ".join(where)

    max_row = sql.fetchone(
        conn,
        f"SELECT MAX(sequence) AS last_sequence FROM llm_execution_events WHERE {where_sql}",
        params,
    )
    last_sequence = int(max_row["last_sequence"] or after) if max_row is not None else after

    stat_rows = sql.fetchall(
        conn,
        f"""
        SELECT event_kind, COUNT(*) AS count
        FROM llm_execution_events
        WHERE {where_sql}
        GROUP BY event_kind
        """,
        params,
    )
    by_kind = {str(row["event_kind"]): int(row["count"]) for row in stat_rows}

    event_where = list(where)
    event_params = dict(params)
    hidden_kinds = normalize_llm_event_kinds(
        hidden_event_kinds if hidden_event_kinds is not None else list(DEFAULT_LLM_HIDDEN_EVENT_KINDS)
    )
    if not include_low_signal:
        if hidden_kinds:
            placeholders: list[str] = []
            for index, kind in enumerate(hidden_kinds):
                key = f"hidden_kind_{index}"
                placeholders.append(f":{key}")
                event_params[key] = kind
            event_where.append(f"event_kind NOT IN ({', '.join(placeholders)})")
    rows = sql.fetchall(
        conn,
        f"""
        SELECT * FROM llm_execution_events
        WHERE {" AND ".join(event_where)}
        ORDER BY sequence DESC
        LIMIT :limit
        """,
        {**event_params, "limit": limit},
    )
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
    params: dict[str, object],
) -> LlmUsageActivity | None:
    usage_count_row = sql.fetchone(
        conn,
        f"SELECT COUNT(*) AS count FROM llm_execution_events WHERE {where_sql} AND event_kind = 'usage'",
        params,
    )
    usage_count = int(usage_count_row["count"] or 0) if usage_count_row is not None else 0
    if usage_count <= 0:
        return None
    row = sql.fetchone(
        conn,
        f"""
        SELECT * FROM llm_execution_events
        WHERE {where_sql} AND event_kind = 'usage'
        ORDER BY sequence DESC
        LIMIT 1
        """,
        params,
    )
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
    sql.execute(
        conn,
        "DELETE FROM llm_execution_events WHERE project_id = :project_id",
        {"project_id": project_id},
    )
    sql.execute(
        conn,
        "DELETE FROM llm_executions WHERE project_id = :project_id",
        {"project_id": project_id},
    )
