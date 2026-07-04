from __future__ import annotations

from cairn.server.application.project_creation import ProjectCreationDraft, create_project_from_draft
from cairn.server.application.project_queries import get_project_detail
from cairn.server.application.replay.attachments import (
    rewrite_attachment_refs,
)
from cairn.server.application.replay.route_extractor import extract_replay_route, intent_source_ids
from cairn.server.application.replay.step_advancer import (
    complete_replay_project,
    create_replay_intent,
    mark_run_completed,
    replay_steps,
    sync_concluded_steps,
)
from cairn.server.domain.errors import ConflictError
from cairn.server.domain.projects import completion_intent_or_409, require_project, require_project_completed
from cairn.server.domain.time import utcnow
from cairn.server.execution_config import execution_capabilities, load_project_execution_configs
from cairn.server.repositories.ids import IdRepository
from cairn.server.repositories.projects import ProjectRepository
from cairn.server.repositories.replay import ReplayRepository
from cairn.server.schemas import (
    CapabilitySelection,
    ReplayRunAdvanceResponse,
    ReplayRunCreateRequest,
)
from cairn.server.schemas.projects import CreateHintInline
from cairn.shared.contracts import hidden_kinds_from_visible, parse_llm_hidden_event_kinds


def create_replay_run_in_transaction(
    conn,
    project_id: str,
    body: ReplayRunCreateRequest,
) -> tuple[str, str]:
    projects = ProjectRepository(conn)
    require_project_completed(projects.get(project_id))
    completion = completion_intent_or_409(projects.completion_intents(project_id))
    completion_source_ids = intent_source_ids(conn, project_id, completion["id"])
    if not completion_source_ids:
        raise ConflictError("Completed project is missing completion source facts")

    route = extract_replay_route(conn, project_id, completion_source_ids)
    if not route:
        raise ConflictError("Completed project has no replayable worker route")

    now = utcnow()
    replay_project_id = IdRepository(conn).next_project_id()
    run_id = f"replay_{replay_project_id}"
    replay_repo = ReplayRepository(conn)
    source_project = require_project(projects.get(project_id))
    llm_hidden_event_kinds = (
        hidden_kinds_from_visible(body.llm_visible_event_kinds)
        if body.llm_visible_event_kinds is not None
        else parse_llm_hidden_event_kinds(
            source_project["llm_hidden_event_kinds"]
            if "llm_hidden_event_kinds" in source_project.keys()
            else None
        )
    )

    replay_capabilities = body.capabilities
    if body.capabilities is None:
        replay_capabilities = {
            task: CapabilitySelection(
                mcp_server_ids=list(selection.user_mcp_server_ids or []),
                skill_ids=list(selection.user_skill_ids or []),
            )
            for task, selection in execution_capabilities(
                load_project_execution_configs(conn, project_id)
            ).items()
        }
    rewritten_hints = [
        CreateHintInline(
            content=rewrite_attachment_refs(hint.content, project_id, replay_project_id),
            creator=hint.creator,
        )
        for hint in body.hints or []
    ]
    create_project_from_draft(
        conn,
        ProjectCreationDraft(
            project_id=replay_project_id,
            title=body.title,
            origin=body.origin,
            goal=body.goal,
            hints=rewritten_hints,
            capabilities=replay_capabilities,
            ai_profiles=body.ai_profiles,
            task_timeouts=body.task_timeouts,
            role_id=body.role_id,
            llm_hidden_event_kinds=llm_hidden_event_kinds,
            status="stopped",
            apply_default_capabilities=False,
        ),
    )
    replay_repo.insert_run(
        run_id=run_id,
        source_project_id=project_id,
        replay_project_id=replay_project_id,
        completion_description=completion["description"],
        created_at=now,
    )
    replay_repo.map_fact(run_id=run_id, source_fact_id="origin", replay_fact_id="origin")
    replay_repo.map_fact(run_id=run_id, source_fact_id="goal", replay_fact_id="goal")
    for index, source_intent in enumerate(route):
        replay_repo.insert_step(
            run_id=run_id,
            step_index=index,
            source_intent_id=source_intent["id"],
            source_to_fact_id=source_intent["to_fact_id"],
        )
    return run_id, replay_project_id


def activate_replay_project(conn, replay_project_id: str):
    ProjectRepository(conn).update_status(replay_project_id, "active")
    return get_project_detail(conn, replay_project_id)


def advance_replay_run_in_transaction(conn, project_id: str):
    run = ReplayRepository(conn).get_run_by_replay_project(project_id)
    if run is None:
        return ReplayRunAdvanceResponse(is_replay=False, action="not_replay", status="not_replay")

    replay_project = require_project(ProjectRepository(conn).get(project_id))
    if replay_project["status"] == "completed" or run["status"] == "completed":
        mark_run_completed(conn, run["id"])
        return ReplayRunAdvanceResponse(
            is_replay=True,
            action="completed",
            status="completed",
            run_id=run["id"],
            project_id=project_id,
        )
    if replay_project["status"] != "active":
        return ReplayRunAdvanceResponse(
            is_replay=True,
            action="blocked",
            status="blocked",
            run_id=run["id"],
            project_id=project_id,
            detail=f"Replay project is {replay_project['status']}",
        )

    sync_concluded_steps(conn, run)
    steps = replay_steps(conn, run["id"])
    active_step = next((step for step in steps if step["status"] == "created"), None)
    if active_step is not None:
        return ReplayRunAdvanceResponse(
            is_replay=True,
            action="waiting",
            status="active",
            run_id=run["id"],
            project_id=project_id,
            intent_id=active_step["replay_intent_id"],
        )

    pending_step = next((step for step in steps if step["status"] == "pending"), None)
    if pending_step is None:
        completed = complete_replay_project(conn, run)
        return ReplayRunAdvanceResponse(
            is_replay=True,
            action="completed",
            status="completed",
            run_id=run["id"],
            project_id=project_id,
            intent_id=completed["id"] if completed is not None else None,
        )

    created = create_replay_intent(conn, run, pending_step)
    if isinstance(created, str):
        return ReplayRunAdvanceResponse(
            is_replay=True,
            action="blocked",
            status="blocked",
            run_id=run["id"],
            project_id=project_id,
            detail=created,
        )
    return ReplayRunAdvanceResponse(
        is_replay=True,
        action="created_intent",
        status="active",
        run_id=run["id"],
        project_id=project_id,
        intent_id=created.id,
    )
