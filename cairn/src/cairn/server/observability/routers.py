from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from cairn.server import db
from cairn.server.observability.models import (
    CreateEventRequest,
    CreateEventResponse,
    CreateEventsBatchRequest,
    CreateEventsBatchResponse,
    CreateExecutionRequest,
    CreateExecutionResponse,
    EventListResponse,
    EventViewResponse,
    ExecutionListResponse,
    FinishExecutionRequest,
    IncrementalEventListResponse,
    ObservabilitySettings,
)
from cairn.server.observability.repository import (
    append_event,
    append_events,
    create_execution,
    finish_execution,
    list_event_view,
    list_execution_events,
    list_executions,
    list_incremental_events,
    list_project_events,
)
from cairn.server.models_pkg.projects import parse_llm_hidden_event_kinds
from cairn.server.repositories import sql

LOG = logging.getLogger(__name__)
router = APIRouter(prefix="/projects/{project_id}", tags=["llm-execution-log"])

SETTINGS = ObservabilitySettings()
MAX_LIMIT = 1000


def _limit(value: int) -> int:
    return min(MAX_LIMIT, max(1, value))


@router.get("/llm-executions", response_model=ExecutionListResponse)
def get_llm_executions(project_id: str, limit: int = Query(default=200, ge=1)):
    with db.session_scope() as conn:
        return ExecutionListResponse(executions=list_executions(conn, project_id, _limit(limit)))


@router.get("/llm-events", response_model=EventListResponse)
def get_project_llm_events(
    project_id: str,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1),
    tail: bool = Query(default=False),
):
    with db.session_scope() as conn:
        return EventListResponse(events=list_project_events(conn, project_id, after, _limit(limit), tail=tail))


@router.get("/llm-events/incremental", response_model=IncrementalEventListResponse)
def get_project_llm_events_incremental(
    project_id: str,
    execution_id: str | None = Query(default=None),
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1),
):
    with db.session_scope() as conn:
        events, last_sequence = list_incremental_events(
            conn,
            project_id,
            execution_id=execution_id,
            after=after,
            limit=_limit(limit),
        )
        return IncrementalEventListResponse(events=events, last_sequence=last_sequence)


@router.get("/llm-events/view", response_model=EventViewResponse)
def get_project_llm_event_view(
    project_id: str,
    execution_id: str | None = Query(default=None),
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=300, ge=1),
    include_low_signal: bool = Query(default=False),
):
    with db.session_scope() as main_conn:
        row = sql.fetchone(
            main_conn,
            "SELECT llm_hidden_event_kinds FROM projects WHERE id = :project_id",
            {"project_id": project_id},
        )
        hidden_event_kinds = parse_llm_hidden_event_kinds(
            row["llm_hidden_event_kinds"] if row is not None else None
        )
    with db.session_scope() as conn:
        return list_event_view(
            conn,
            project_id,
            execution_id=execution_id,
            after=after,
            limit=_limit(limit),
            include_low_signal=include_low_signal,
            hidden_event_kinds=hidden_event_kinds,
        )


@router.get("/llm-executions/{execution_id}/events", response_model=EventListResponse)
def get_execution_llm_events(
    project_id: str,
    execution_id: str,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1),
    tail: bool = Query(default=False),
):
    with db.session_scope() as conn:
        return EventListResponse(events=list_execution_events(conn, project_id, execution_id, after, _limit(limit), tail=tail))


@router.post("/llm-executions", response_model=CreateExecutionResponse, status_code=201)
def post_llm_execution(project_id: str, body: CreateExecutionRequest):
    with db.session_scope() as conn:
        return CreateExecutionResponse(execution=create_execution(conn, project_id, body))


@router.post("/llm-executions/{execution_id}/events", response_model=CreateEventResponse, status_code=201)
def post_llm_event(project_id: str, execution_id: str, body: CreateEventRequest):
    with db.session_scope() as conn:
        event, dropped = append_event(conn, project_id, execution_id, body, SETTINGS)
        return CreateEventResponse(event=event, dropped=dropped)


@router.post("/llm-executions/{execution_id}/events/batch", response_model=CreateEventsBatchResponse, status_code=201)
def post_llm_events_batch(project_id: str, execution_id: str, body: CreateEventsBatchRequest):
    with db.session_scope() as conn:
        events, dropped = append_events(conn, project_id, execution_id, body.events, SETTINGS)
        return CreateEventsBatchResponse(events=events, dropped=dropped)


@router.post("/llm-executions/{execution_id}/finish", response_model=CreateExecutionResponse)
def post_llm_execution_finish(project_id: str, execution_id: str, body: FinishExecutionRequest):
    with db.session_scope() as conn:
        execution = finish_execution(conn, project_id, execution_id, body)
        if execution is None:
            execution = create_execution(
                conn,
                project_id,
                CreateExecutionRequest(id=execution_id, intent_id=None, task_type="reason", worker="unknown"),
            )
            execution = finish_execution(conn, project_id, execution_id, body) or execution
        return CreateExecutionResponse(execution=execution)
