from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from cairn.server import db
from cairn.server.observability.events_query import (
    list_execution_events,
    list_incremental_events,
    list_project_events,
)
from cairn.server.observability.event_card_service import list_event_cards
from cairn.server.observability.events_writer import (
    append_event,
    append_events,
)
from cairn.server.observability.executions import (
    create_execution,
    finish_execution,
    list_executions,
)
from cairn.server.observability.models import (
    CreateEventRequest,
    CreateEventResponse,
    CreateEventsBatchRequest,
    CreateEventsBatchResponse,
    CreateExecutionRequest,
    CreateExecutionResponse,
    EventCardPageResponse,
    EventListResponse,
    EventViewResponse,
    ExecutionListResponse,
    FinishExecutionRequest,
    IncrementalEventListResponse,
    ObservabilitySettings,
)
from cairn.server.observability.view_service import list_event_view

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
    event_kinds: list[str] | None = Query(default=None),
):
    with db.session_scope() as conn:
        events, last_sequence = list_incremental_events(
            conn,
            project_id,
            execution_id=execution_id,
            after=after,
            limit=_limit(limit),
            event_kinds=event_kinds,
        )
        return IncrementalEventListResponse(events=events, last_sequence=last_sequence)


@router.get("/llm-events/cards", response_model=EventCardPageResponse)
def get_project_llm_event_cards(
    project_id: str,
    execution_id: str | None = Query(default=None),
    page_size: int = Query(default=12, ge=1),
    page_token: str | None = Query(default=None),
    event_kinds: list[str] | None = Query(default=None),
):
    try:
        with db.session_scope() as conn:
            return list_event_cards(
                conn,
                project_id,
                execution_id=execution_id,
                page_size=_limit(page_size),
                page_token=page_token,
                event_kinds=event_kinds,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/llm-events/view", response_model=EventViewResponse)
def get_project_llm_event_view(
    project_id: str,
    execution_id: str | None = Query(default=None),
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=300, ge=1),
    event_kinds: list[str] | None = Query(default=None),
):
    with db.session_scope() as conn:
        return list_event_view(
            conn,
            project_id,
            execution_id=execution_id,
            after=after,
            limit=_limit(limit),
            event_kinds=event_kinds,
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
