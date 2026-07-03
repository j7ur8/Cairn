from fastapi import APIRouter, Query

from cairn.server import db
from cairn.server.application.project_commands import (
    complete_project as complete_project_command,
)
from cairn.server.application.project_commands import (
    delete_project as delete_project_command,
)
from cairn.server.application.project_commands import (
    delete_project_observability_best_effort,
)
from cairn.server.application.project_commands import (
    reopen_project as reopen_project_command,
)
from cairn.server.application.project_commands import (
    update_project_status as update_project_status_command,
)
from cairn.server.application.project_commands import (
    update_project_title as update_project_title_command,
)
from cairn.server.application.project_creation import (
    ProjectCreationDraft,
    create_project_from_draft,
)
from cairn.server.application.project_queries import (
    get_project_detail,
    get_project_graph_delta,
    get_project_poll_state,
    list_project_summaries,
    list_project_summaries_page,
    list_project_work_summaries,
    list_project_work_summaries_page,
)
from cairn.server.application.reason_commands import (
    claim_reason,
    finish_reason,
    heartbeat_reason,
    reason_state,
    release_reason,
)
from cairn.server.schemas import (
    CompleteRequest,
    CreateProjectRequest,
    HeartbeatRequest,
    ProjectPollStateResponse,
    ReasonClaimRequest,
    ReasonFinishRequest,
    ReasonState,
    ReopenRequest,
    ReopenResponse,
    UpdateProjectStatusRequest,
    UpdateProjectTitleRequest,
)
from cairn.shared.contracts import (
    Intent,
    ProjectDetail,
    ProjectGraphDelta,
    ProjectMeta,
    ProjectSummary,
    ProjectSummaryPage,
    ProjectWorkSummary,
    ProjectWorkSummaryPage,
)

router = APIRouter(tags=["projects"])


@router.get("/projects", response_model=list[ProjectSummary] | ProjectSummaryPage)
def list_projects(limit: int | None = Query(default=None, ge=1, le=200), cursor: str | None = None):
    with db.session_scope() as conn:
        if limit is not None:
            return list_project_summaries_page(conn, limit=limit, cursor=cursor)
        return list_project_summaries(conn)


@router.get("/projects/work", response_model=list[ProjectWorkSummary] | ProjectWorkSummaryPage)
def list_project_work(limit: int | None = Query(default=None, ge=1, le=200), cursor: str | None = None):
    with db.session_scope() as conn:
        if limit is not None:
            return list_project_work_summaries_page(conn, limit=limit, cursor=cursor)
        return list_project_work_summaries(conn)


@router.post("/projects", response_model=ProjectDetail, status_code=201)
def create_project(body: CreateProjectRequest):
    with db.session_scope() as conn:
        return create_project_from_draft(
            conn,
            ProjectCreationDraft(
                title=body.title,
                origin=body.origin,
                goal=body.goal,
                hints=body.hints,
                capabilities=body.capabilities,
                ai_profiles=body.ai_profiles,
                task_timeouts=body.task_timeouts,
                role_id=body.role_id,
                llm_visible_event_kinds=body.llm_visible_event_kinds,
                status="active",
            ),
        )


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str):
    with db.session_scope() as conn:
        return get_project_detail(conn, project_id)


@router.get("/projects/{project_id}/poll-state", response_model=ProjectPollStateResponse)
def get_project_poll(project_id: str):
    with db.session_scope() as conn:
        return get_project_poll_state(conn, project_id)


@router.get("/projects/{project_id}/graph", response_model=ProjectGraphDelta)
def get_project_graph(
    project_id: str,
    after_graph_revision: int | None = Query(default=None, ge=0),
    after_timeline_revision: int | None = Query(default=None, ge=0),
):
    with db.session_scope() as conn:
        return get_project_graph_delta(
            conn,
            project_id,
            after_graph_revision=after_graph_revision,
            after_timeline_revision=after_timeline_revision,
        )


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str):
    with db.session_scope() as conn:
        delete_project_command(conn, project_id)
    delete_project_observability_best_effort(project_id)


@router.put("/projects/{project_id}/title", response_model=ProjectMeta)
def update_project_title(project_id: str, body: UpdateProjectTitleRequest):
    with db.session_scope() as conn:
        return update_project_title_command(conn, project_id, body)


@router.put("/projects/{project_id}/status", response_model=ProjectMeta)
def update_project_status(project_id: str, body: UpdateProjectStatusRequest):
    with db.session_scope() as conn:
        return update_project_status_command(conn, project_id, body)


@router.post("/projects/{project_id}/reason/claim", response_model=ProjectMeta)
def claim_project_reason(project_id: str, body: ReasonClaimRequest):
    with db.session_scope() as conn:
        return claim_reason(conn, project_id, body)


@router.post("/projects/{project_id}/reason/heartbeat", response_model=ProjectMeta)
def heartbeat_project_reason(project_id: str, body: HeartbeatRequest):
    with db.session_scope() as conn:
        return heartbeat_reason(conn, project_id, body)


@router.post("/projects/{project_id}/reason/release", response_model=ProjectMeta)
def release_project_reason(project_id: str, body: HeartbeatRequest):
    with db.session_scope() as conn:
        return release_reason(conn, project_id, body)


@router.get("/projects/{project_id}/reason/state", response_model=ReasonState | None)
def get_reason_state(project_id: str):
    with db.session_scope() as conn:
        return reason_state(conn, project_id)


@router.post("/projects/{project_id}/reason/finish", response_model=ProjectMeta)
def finish_project_reason(project_id: str, body: ReasonFinishRequest):
    with db.session_scope() as conn:
        return finish_reason(conn, project_id, body)


@router.post("/projects/{project_id}/complete", response_model=Intent)
def complete_project(project_id: str, body: CompleteRequest):
    with db.session_scope() as conn:
        return complete_project_command(conn, project_id, body)


@router.post("/projects/{project_id}/reopen", response_model=ReopenResponse)
def reopen_project(project_id: str, body: ReopenRequest):
    with db.session_scope() as conn:
        return reopen_project_command(conn, project_id, body)
