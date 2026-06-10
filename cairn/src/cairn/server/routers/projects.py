import logging

from fastapi import APIRouter, HTTPException

from cairn.server import db
from cairn.server.observability.repository import delete_project_observability
from cairn.server.models_pkg.intents import (
    CompleteRequest,
    CreateProjectRequest,
    HeartbeatRequest,
    ReopenRequest,
    ReopenResponse,
    ReasonClaimRequest,
    ReasonFinishRequest,
    ReasonState,
    UpdateProjectTitleRequest,
    UpdateProjectStatusRequest,
)
from cairn.server.models_pkg.projects import Fact, Hint, Intent, ProjectDetail, ProjectMeta, ProjectSummary
from cairn.server.models_pkg.proxies import ProxySummary
from cairn.server.project_creation_service import (
    ProjectCreationDraft,
    create_project_from_draft,
    proxy_summary_from_row,
)
from cairn.server.repositories.intents import IntentRepository
from cairn.server.repositories.projects import ProjectRepository
from cairn.server.config.proxies import get_yaml_proxy
from cairn.server.services import (
    build_intents,
    check_project_completed,
    check_project_active,
    claim_project_reason_or_409,
    clear_project_reason,
    expire_reason_leases,
    expire_workers,
    finish_project_reason_or_409,
    get_completion_intent_or_409,
    get_project_or_404,
    get_project_reason_state,
    heartbeat_project_reason_or_409,
    intent_to_model,
    next_fact_id,
    next_project_id,
    next_intent_id,
    project_meta_from_row,
    project_reason_from_row,
    reason_trigger_hash,
    release_project_reason_or_409,
    utcnow,
    validate_facts_exist,
    validate_goal_not_in_sources,
)

router = APIRouter(tags=["projects"])
LOG = logging.getLogger(__name__)


@router.get("/projects", response_model=list[ProjectSummary])
def list_projects():
    with db.session_scope() as conn:
        expire_workers(conn)
        expire_reason_leases(conn)
        rows = ProjectRepository(conn).list_with_counts()
        return [
            ProjectSummary(
                id=row["id"],
                title=row["title"],
                status=row["status"],
                created_at=row["created_at"],
                reason=project_reason_from_row(row),
                fact_count=row["fact_count"],
                intent_count=row["intent_count"],
                working_intent_count=row["working_intent_count"],
                unclaimed_intent_count=row["unclaimed_intent_count"],
                hint_count=row["hint_count"],
            )
            for row in rows
        ]


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
                role_id=body.role_id,
                proxy_id=body.proxy_id,
                llm_visible_event_kinds=body.llm_visible_event_kinds,
                status="active",
            ),
        )


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str):
    with db.session_scope() as conn:
        expire_workers(conn, project_id)
        expire_reason_leases(conn, project_id)
        row = get_project_or_404(conn, project_id)
        projects = ProjectRepository(conn)

        facts = projects.get_facts(project_id)
        hints = projects.get_hints(project_id)

        proxy_summary: ProxySummary | None = None
        if row["proxy_id"]:
            try:
                proxy = get_yaml_proxy(row["proxy_id"])
                proxy_summary = ProxySummary(
                    id=proxy.id,
                    name=proxy.name,
                    type=proxy.type,
                    host=proxy.host,
                    port=proxy.port,
                    has_auth=proxy.has_auth,
                    created_at=proxy.created_at,
                    updated_at=proxy.updated_at,
                )
            except HTTPException:
                proxy_summary = None

        return ProjectDetail(
            project=project_meta_from_row(row),
            facts=[Fact(**dict(f)) for f in facts],
            intents=build_intents(conn, project_id),
            hints=[Hint(**dict(h)) for h in hints],
            proxy=proxy_summary,
        )


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str):
    with db.session_scope() as conn:
        get_project_or_404(conn, project_id)
        ProjectRepository(conn).delete(project_id)
    try:
        with db.session_scope() as obs_conn:
            delete_project_observability(obs_conn, project_id)
    except Exception as exc:
        LOG.warning("observability cleanup failed project=%s error=%s", project_id, exc)


@router.put("/projects/{project_id}/title", response_model=ProjectMeta)
def update_project_title(project_id: str, body: UpdateProjectTitleRequest):
    with db.session_scope() as conn:
        get_project_or_404(conn, project_id)
        updated = ProjectRepository(conn).update_title(project_id, body.title)
        return project_meta_from_row(updated)


@router.put("/projects/{project_id}/status", response_model=ProjectMeta)
def update_project_status(project_id: str, body: UpdateProjectStatusRequest):
    with db.session_scope() as conn:
        expire_reason_leases(conn, project_id)
        row = get_project_or_404(conn, project_id)
        current_status = row["status"]
        if current_status == "completed":
            raise HTTPException(409, "Completed projects cannot change status")
        if current_status == body.status:
            return project_meta_from_row(row)

        projects = ProjectRepository(conn)
        projects.update_status(project_id, body.status)
        if body.status == "stopped":
            projects.release_open_intents(project_id)
            clear_project_reason(conn, project_id)
        updated = projects.get(project_id)
        return project_meta_from_row(updated)


@router.post("/projects/{project_id}/reason/claim", response_model=ProjectMeta)
def claim_project_reason(project_id: str, body: ReasonClaimRequest):
    with db.session_scope() as conn:
        now = utcnow()
        updated = claim_project_reason_or_409(
            conn,
            project_id,
            body.worker,
            body.trigger,
            now,
            run_id=body.run_id,
            trigger_hash=body.trigger_hash or reason_trigger_hash(body.trigger),
            fact_count=body.fact_count,
            hint_count=body.hint_count,
            open_intent_count=body.open_intent_count,
        )
        return project_meta_from_row(updated)


@router.post("/projects/{project_id}/reason/heartbeat", response_model=ProjectMeta)
def heartbeat_project_reason(project_id: str, body: HeartbeatRequest):
    with db.session_scope() as conn:
        now = utcnow()
        updated = heartbeat_project_reason_or_409(conn, project_id, body.worker, now, body.run_id)
        return project_meta_from_row(updated)


@router.post("/projects/{project_id}/reason/release", response_model=ProjectMeta)
def release_project_reason(project_id: str, body: HeartbeatRequest):
    with db.session_scope() as conn:
        updated = release_project_reason_or_409(conn, project_id, body.worker, body.run_id)
        return project_meta_from_row(updated)


@router.get("/projects/{project_id}/reason/state", response_model=ReasonState | None)
def get_reason_state(project_id: str):
    with db.session_scope() as conn:
        get_project_or_404(conn, project_id)
        return get_project_reason_state(conn, project_id)


@router.post("/projects/{project_id}/reason/finish", response_model=ProjectMeta)
def finish_project_reason(project_id: str, body: ReasonFinishRequest):
    with db.session_scope() as conn:
        now = utcnow()
        updated = finish_project_reason_or_409(
            conn,
            project_id,
            body.worker,
            body.trigger,
            now,
            run_id=body.run_id,
            trigger_hash=body.trigger_hash or reason_trigger_hash(body.trigger),
            fact_count=body.fact_count,
            hint_count=body.hint_count,
            open_intent_count=body.open_intent_count,
            outcome=body.outcome,
            error=body.error,
        )
        return project_meta_from_row(updated)


@router.post("/projects/{project_id}/complete", response_model=Intent)
def complete_project(project_id: str, body: CompleteRequest):
    with db.session_scope() as conn:
        check_project_active(conn, project_id)
        expire_reason_leases(conn, project_id)
        validate_facts_exist(conn, project_id, body.from_)
        validate_goal_not_in_sources(body.from_)

        now = utcnow()
        iid = next_intent_id(conn, project_id)

        IntentRepository(conn).insert_completed_goal(
            project_id=project_id,
            intent_id=iid,
            source_fact_ids=body.from_,
            description=body.description,
            worker=body.worker,
            now=now,
        )
        ProjectRepository(conn).complete(project_id)

        return Intent(
            id=iid,
            **{"from": body.from_},
            to="goal",
            description=body.description,
            creator=body.worker,
            worker=body.worker,
            last_heartbeat_at=now,
            created_at=now,
            concluded_at=now,
        )


@router.post("/projects/{project_id}/reopen", response_model=ReopenResponse)
def reopen_project(project_id: str, body: ReopenRequest):
    with db.session_scope() as conn:
        expire_reason_leases(conn, project_id)
        check_project_completed(conn, project_id)
        completion = get_completion_intent_or_409(conn, project_id)
        intents = IntentRepository(conn)

        source_ids = intents.source_fact_ids(project_id, completion["id"])
        if not source_ids:
            raise HTTPException(409, "Completion intent is missing its source facts")

        now = utcnow()
        fact_id = next_fact_id(conn, project_id)
        intent_id = next_intent_id(conn, project_id)
        description = body.description
        creator = body.creator

        intents.delete_intent(project_id, completion["id"])
        intents.insert_fact(project_id, fact_id, description)
        intents.insert_concluded(
            project_id=project_id,
            intent_id=intent_id,
            to_fact_id=fact_id,
            source_fact_ids=source_ids,
            description="external_feedback",
            creator=creator,
            now=now,
        )
        clear_project_reason(conn, project_id)
        projects = ProjectRepository(conn)
        updated_project = projects.reopen(project_id)

        updated_intent = intents.get_intent(project_id, intent_id)
        assert updated_project is not None
        assert updated_intent is not None
        return ReopenResponse(
            project=project_meta_from_row(updated_project),
            fact=Fact(id=fact_id, description=description),
            intent=intent_to_model(conn, updated_intent, project_id),
        )
