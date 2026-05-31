from __future__ import annotations

import json
import sqlite3

from cairn.server.observability.models import (
    CreateEventRequest,
    CreateExecutionRequest,
    FinishExecutionRequest,
    LlmExecution,
    LlmExecutionEvent,
    ObservabilitySettings,
)
from cairn.server.observability.redaction import redact_content, truncate_content
from cairn.server.services import utcnow


def row_to_execution(row: sqlite3.Row) -> LlmExecution:
    return LlmExecution(**dict(row))


def row_to_event(row: sqlite3.Row) -> LlmExecutionEvent:
    return LlmExecutionEvent(**dict(row))


def create_execution(conn: sqlite3.Connection, project_id: str, body: CreateExecutionRequest) -> LlmExecution:
    now = utcnow()
    conn.execute(
        """
        INSERT OR REPLACE INTO llm_executions (
            id, project_id, intent_id, task_type, worker, process_state,
            started_at, ended_at, last_event_at, event_count, bytes_written,
            returncode, timed_out, error_kind, produced_fact_id, created_intent_ids
        ) VALUES (?, ?, ?, ?, ?, 'running', ?, NULL, NULL, 0, 0, NULL, 0, NULL, NULL, NULL)
        """,
        (body.id, project_id, body.intent_id, body.task_type, body.worker, now),
    )
    row = conn.execute("SELECT * FROM llm_executions WHERE id = ?", (body.id,)).fetchone()
    assert row is not None
    return row_to_execution(row)


def list_executions(conn: sqlite3.Connection, project_id: str, limit: int) -> list[LlmExecution]:
    rows = conn.execute(
        """
        SELECT * FROM llm_executions
        WHERE project_id = ?
        ORDER BY started_at DESC, id DESC
        LIMIT ?
        """,
        (project_id, limit),
    ).fetchall()
    return [row_to_execution(row) for row in rows]


def append_event(
    conn: sqlite3.Connection,
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
        (cursor.lastrowid,),
    ).fetchone()
    assert row is not None
    return row_to_event(row), False


def finish_execution(
    conn: sqlite3.Connection,
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
    return row_to_execution(row) if row is not None else None


def list_project_events(conn: sqlite3.Connection, project_id: str, after: int, limit: int) -> list[LlmExecutionEvent]:
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
    conn: sqlite3.Connection,
    project_id: str,
    execution_id: str,
    after: int,
    limit: int,
) -> list[LlmExecutionEvent]:
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


def delete_project_observability(conn: sqlite3.Connection, project_id: str) -> None:
    conn.execute("DELETE FROM llm_execution_events WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM llm_executions WHERE project_id = ?", (project_id,))
