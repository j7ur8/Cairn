from __future__ import annotations

import json
from typing import Any

from cairn.server.domain.time import utcnow
from cairn.server.observability._shared import row_to_execution
from cairn.server.observability.event_repository import LlmEventRepository
from cairn.server.observability.execution_repository import LlmExecutionRepository
from cairn.server.observability.models import (
    CreateExecutionRequest,
    FinishExecutionRequest,
    LlmExecution,
)


def create_execution(conn: Any, project_id: str, body: CreateExecutionRequest) -> LlmExecution:
    now = utcnow()
    repo = LlmExecutionRepository(conn)
    repo.upsert_running(
        execution_id=body.id,
        project_id=project_id,
        intent_id=body.intent_id,
        task_type=body.task_type,
        worker=body.worker,
        started_at=now,
    )
    row = repo.get(body.id)
    assert row is not None
    return row_to_execution(row)


def list_executions(conn: Any, project_id: str, limit: int) -> list[LlmExecution]:
    rows = LlmExecutionRepository(conn).list_for_project(project_id, limit)
    return [row_to_execution(row) for row in rows]


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
    repo = LlmExecutionRepository(conn)
    repo.finish(
        project_id=project_id,
        execution_id=execution_id,
        process_state=body.process_state,
        ended_at=now,
        returncode=body.returncode,
        timed_out=body.timed_out,
        error_kind=body.error_kind,
        produced_fact_id=body.produced_fact_id,
        created_intent_ids=created_intent_ids,
    )
    row = repo.get(execution_id, project_id)
    if row is not None:
        ensure_process_end_event(conn, row, body, now)
    return row_to_execution(row) if row is not None else None


def ensure_process_end_event(
    conn: Any,
    execution: Any,
    body: FinishExecutionRequest,
    now: str,
) -> None:
    events = LlmEventRepository(conn)
    if events.has_process_end_event(execution["id"]):
        return
    content = (
        f"process_state={body.process_state} returncode={body.returncode} "
        f"timed_out={body.timed_out} error_kind={body.error_kind or ''}"
    )
    byte_count = len(content.encode("utf-8"))
    events.insert_process_end_event(
        execution=execution,
        content=content,
        created_at=now,
    )
    LlmExecutionRepository(conn).increment_event_stats(
        execution_id=execution["id"],
        last_event_at=now,
        event_count=1,
        byte_count=byte_count,
    )


def delete_project_observability(conn: Any, project_id: str) -> None:
    LlmEventRepository(conn).delete_project(project_id)
    LlmExecutionRepository(conn).delete_project(project_id)
