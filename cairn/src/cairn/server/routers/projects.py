import logging

from fastapi import APIRouter, HTTPException

from cairn.server.db import get_conn, with_immediate_tx
from cairn.server.observability import db as observability_db
from cairn.server.observability.repository import delete_project_observability
from cairn.server.models import (
    CompleteRequest,
    CreateProjectRequest,
    Fact,
    Hint,
    HeartbeatRequest,
    Intent,
    ProjectDetail,
    ProjectMeta,
    ProjectSummary,
    ProxySummary,
    ReopenRequest,
    ReopenResponse,
    ReasonClaimRequest,
    ReasonFinishRequest,
    ReasonState,
    UpdateProjectTitleRequest,
    UpdateProjectStatusRequest,
)
from cairn.server.project_creation_service import (
    ProjectCreationDraft,
    create_project_from_draft,
    proxy_summary_from_row,
)
from cairn.server.yaml_config import get_yaml_proxy
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
    with get_conn() as conn:
        expire_workers(conn)
        expire_reason_leases(conn)
        rows = conn.execute("""
            SELECT p.*,
                (SELECT COUNT(*) FROM facts WHERE project_id = p.id) AS fact_count,
                (SELECT COUNT(*) FROM intents WHERE project_id = p.id) AS intent_count,
                (SELECT COUNT(*) FROM intents WHERE project_id = p.id AND concluded_at IS NULL AND worker IS NOT NULL) AS working_intent_count,
                (SELECT COUNT(*) FROM intents WHERE project_id = p.id AND concluded_at IS NULL AND worker IS NULL) AS unclaimed_intent_count,
                (SELECT COUNT(*) FROM hints WHERE project_id = p.id) AS hint_count
            FROM projects p
            ORDER BY p.created_at
        """).fetchall()
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
    with with_immediate_tx() as conn:
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
    with get_conn() as conn:
        expire_workers(conn, project_id)
        expire_reason_leases(conn, project_id)
        row = get_project_or_404(conn, project_id)

        facts = conn.execute(
            "SELECT * FROM facts WHERE project_id = ?", (project_id,)
        ).fetchall()
        hints = conn.execute(
            "SELECT * FROM hints WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()

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
    with with_immediate_tx() as conn:
        get_project_or_404(conn, project_id)
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    try:
        with observability_db.get_conn() as obs_conn:
            delete_project_observability(obs_conn, project_id)
    except Exception as exc:
        LOG.warning("observability cleanup failed project=%s error=%s", project_id, exc)


@router.put("/projects/{project_id}/title", response_model=ProjectMeta)
def update_project_title(project_id: str, body: UpdateProjectTitleRequest):
    with with_immediate_tx() as conn:
        get_project_or_404(conn, project_id)
        conn.execute(
            "UPDATE projects SET title = ? WHERE id = ?",
            (body.title, project_id),
        )
        updated = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return project_meta_from_row(updated)


@router.put("/projects/{project_id}/status", response_model=ProjectMeta)
def update_project_status(project_id: str, body: UpdateProjectStatusRequest):
    with with_immediate_tx() as conn:
        expire_reason_leases(conn, project_id)
        row = get_project_or_404(conn, project_id)
        current_status = row["status"]
        if current_status == "completed":
            raise HTTPException(409, "Completed projects cannot change status")
        if current_status == body.status:
            return project_meta_from_row(row)

        conn.execute(
            "UPDATE projects SET status = ? WHERE id = ?",
            (body.status, project_id),
        )
        if body.status == "stopped":
            conn.execute(
                "UPDATE intents SET worker = NULL WHERE project_id = ? AND concluded_at IS NULL",
                (project_id,),
            )
            clear_project_reason(conn, project_id)
        updated = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return project_meta_from_row(updated)


@router.post("/projects/{project_id}/reason/claim", response_model=ProjectMeta)
def claim_project_reason(project_id: str, body: ReasonClaimRequest):
    with with_immediate_tx() as conn:
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
    with with_immediate_tx() as conn:
        now = utcnow()
        updated = heartbeat_project_reason_or_409(conn, project_id, body.worker, now, body.run_id)
        return project_meta_from_row(updated)


@router.post("/projects/{project_id}/reason/release", response_model=ProjectMeta)
def release_project_reason(project_id: str, body: HeartbeatRequest):
    with with_immediate_tx() as conn:
        updated = release_project_reason_or_409(conn, project_id, body.worker, body.run_id)
        return project_meta_from_row(updated)


@router.get("/projects/{project_id}/reason/state", response_model=ReasonState | None)
def get_reason_state(project_id: str):
    with get_conn() as conn:
        get_project_or_404(conn, project_id)
        return get_project_reason_state(conn, project_id)


@router.post("/projects/{project_id}/reason/finish", response_model=ProjectMeta)
def finish_project_reason(project_id: str, body: ReasonFinishRequest):
    with with_immediate_tx() as conn:
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
    with with_immediate_tx() as conn:
        check_project_active(conn, project_id)
        expire_reason_leases(conn, project_id)
        validate_facts_exist(conn, project_id, body.from_)
        validate_goal_not_in_sources(body.from_)

        now = utcnow()
        iid = next_intent_id(conn, project_id)

        conn.execute(
            "INSERT INTO intents (id, project_id, to_fact_id, description, creator, worker, last_heartbeat_at, created_at, concluded_at) VALUES (?, ?, 'goal', ?, ?, ?, ?, ?, ?)",
            (iid, project_id, body.description, body.worker, body.worker, now, now, now),
        )
        for fid in body.from_:
            conn.execute(
                "INSERT INTO intent_sources (intent_id, project_id, fact_id) VALUES (?, ?, ?)",
                (iid, project_id, fid),
            )
        conn.execute(
            """
            UPDATE projects
            SET status = 'completed',
                reason_worker = NULL,
                reason_run_id = NULL,
                reason_trigger = NULL,
                reason_started_at = NULL,
                reason_last_heartbeat_at = NULL
            WHERE id = ?
            """,
            (project_id,),
        )

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
    with with_immediate_tx() as conn:
        expire_reason_leases(conn, project_id)
        check_project_completed(conn, project_id)
        completion = get_completion_intent_or_409(conn, project_id)

        source_rows = conn.execute(
            "SELECT fact_id FROM intent_sources WHERE intent_id = ? AND project_id = ? ORDER BY rowid",
            (completion["id"], project_id),
        ).fetchall()
        source_ids = [row["fact_id"] for row in source_rows]
        if not source_ids:
            raise HTTPException(409, "Completion intent is missing its source facts")

        now = utcnow()
        fact_id = next_fact_id(conn, project_id)
        intent_id = next_intent_id(conn, project_id)
        description = body.description
        creator = body.creator

        conn.execute(
            "DELETE FROM intents WHERE id = ? AND project_id = ?",
            (completion["id"], project_id),
        )
        conn.execute(
            "INSERT INTO facts (id, project_id, description) VALUES (?, ?, ?)",
            (fact_id, project_id, description),
        )
        conn.execute(
            "INSERT INTO intents (id, project_id, to_fact_id, description, creator, worker, last_heartbeat_at, created_at, concluded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (intent_id, project_id, fact_id, "external_feedback", creator, creator, now, now, now),
        )
        for source_id in source_ids:
            conn.execute(
                "INSERT INTO intent_sources (intent_id, project_id, fact_id) VALUES (?, ?, ?)",
                (intent_id, project_id, source_id),
            )
        clear_project_reason(conn, project_id)
        conn.execute(
            "UPDATE projects SET status = 'active' WHERE id = ?",
            (project_id,),
        )

        updated_project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        updated_intent = conn.execute(
            "SELECT * FROM intents WHERE id = ? AND project_id = ?",
            (intent_id, project_id),
        ).fetchone()
        assert updated_project is not None
        assert updated_intent is not None
        return ReopenResponse(
            project=project_meta_from_row(updated_project),
            fact=Fact(id=fact_id, description=description),
            intent=intent_to_model(conn, updated_intent, project_id),
        )
