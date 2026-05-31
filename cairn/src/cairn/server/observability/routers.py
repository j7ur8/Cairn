from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from cairn.server.observability import db
from cairn.server.observability.models import (
    CreateEventRequest,
    CreateEventResponse,
    CreateExecutionRequest,
    CreateExecutionResponse,
    EventListResponse,
    ExecutionListResponse,
    FinishExecutionRequest,
    ObservabilitySettings,
)
from cairn.server.observability.repository import (
    append_event,
    create_execution,
    finish_execution,
    list_execution_events,
    list_executions,
    list_project_events,
)

LOG = logging.getLogger(__name__)
router = APIRouter(prefix="/projects/{project_id}", tags=["llm-execution-log"])

SETTINGS = ObservabilitySettings()
MAX_LIMIT = 1000


def _limit(value: int) -> int:
    return min(MAX_LIMIT, max(1, value))


@router.get("/llm-executions", response_model=ExecutionListResponse)
def get_llm_executions(project_id: str, limit: int = Query(default=200, ge=1)):
    with db.get_conn() as conn:
        return ExecutionListResponse(executions=list_executions(conn, project_id, _limit(limit)))


@router.get("/llm-events", response_model=EventListResponse)
def get_project_llm_events(
    project_id: str,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1),
):
    with db.get_conn() as conn:
        return EventListResponse(events=list_project_events(conn, project_id, after, _limit(limit)))


@router.get("/llm-executions/{execution_id}/events", response_model=EventListResponse)
def get_execution_llm_events(
    project_id: str,
    execution_id: str,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1),
):
    with db.get_conn() as conn:
        return EventListResponse(events=list_execution_events(conn, project_id, execution_id, after, _limit(limit)))


@router.post("/llm-executions", response_model=CreateExecutionResponse, status_code=201)
def post_llm_execution(project_id: str, body: CreateExecutionRequest):
    with db.get_conn() as conn:
        return CreateExecutionResponse(execution=create_execution(conn, project_id, body))


@router.post("/llm-executions/{execution_id}/events", response_model=CreateEventResponse, status_code=201)
def post_llm_event(project_id: str, execution_id: str, body: CreateEventRequest):
    with db.get_conn() as conn:
        event, dropped = append_event(conn, project_id, execution_id, body, SETTINGS)
        return CreateEventResponse(event=event, dropped=dropped)


@router.post("/llm-executions/{execution_id}/finish", response_model=CreateExecutionResponse)
def post_llm_execution_finish(project_id: str, execution_id: str, body: FinishExecutionRequest):
    with db.get_conn() as conn:
        execution = finish_execution(conn, project_id, execution_id, body)
        if execution is None:
            execution = create_execution(
                conn,
                project_id,
                CreateExecutionRequest(id=execution_id, intent_id=None, task_type="reason", worker="unknown"),
            )
            execution = finish_execution(conn, project_id, execution_id, body) or execution
        return CreateExecutionResponse(execution=execution)
