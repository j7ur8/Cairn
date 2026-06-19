from __future__ import annotations

import logging
from typing import Any

from cairn.server import db
from cairn.server.domain.errors import ConflictError
from cairn.server.domain.projects import (
    completion_intent_or_409,
    require_project,
    require_project_active,
    require_project_completed,
    should_update_project_status,
    validate_facts_exist,
    validate_goal_not_in_sources,
)
from cairn.server.domain.time import utcnow
from cairn.server.mappers.intents import intent_to_model
from cairn.server.mappers.projects import project_meta_from_row
from cairn.server.models_pkg import (
    CompleteRequest,
    ReopenRequest,
    ReopenResponse,
    UpdateProjectStatusRequest,
    UpdateProjectTitleRequest,
)
from cairn.server.observability.executions import delete_project_observability
from cairn.server.repositories.ids import IdRepository
from cairn.server.repositories.intents import IntentRepository
from cairn.server.repositories.leases import LeaseRepository
from cairn.server.repositories.projects import ProjectRepository
from cairn.server.repositories.reason import ReasonRepository
from cairn.shared.contracts import Fact, Intent, ProjectMeta

LOG = logging.getLogger(__name__)


def delete_project(conn: Any, project_id: str) -> None:
    require_project(ProjectRepository(conn).get(project_id))
    ProjectRepository(conn).delete(project_id)


def delete_project_observability_best_effort(project_id: str) -> None:
    try:
        with db.session_scope() as obs_conn:
            delete_project_observability(obs_conn, project_id)
    except Exception as exc:  # noqa: BLE001 - deletion is best-effort cleanup.
        LOG.warning("observability cleanup failed project=%s error=%s", project_id, exc)


def update_project_title(conn: Any, project_id: str, body: UpdateProjectTitleRequest) -> ProjectMeta:
    projects = ProjectRepository(conn)
    require_project(projects.get(project_id))
    updated = projects.update_title(project_id, body.title)
    projects.bump_revisions(project_id, timeline=True)
    updated = projects.get(project_id)
    return project_meta_from_row(updated)


def update_project_status(conn: Any, project_id: str, body: UpdateProjectStatusRequest) -> ProjectMeta:
    LeaseRepository(conn).expire_reason_leases(project_id)
    row = require_project(ProjectRepository(conn).get(project_id))
    if not should_update_project_status(row, body.status):
        return project_meta_from_row(row)

    projects = ProjectRepository(conn)
    projects.update_status(project_id, body.status)
    if body.status == "stopped":
        projects.release_open_intents(project_id)
        ReasonRepository(conn).clear_project_reason(project_id)
        projects.bump_revisions(project_id, graph=True, timeline=True)
    else:
        projects.bump_revisions(project_id, timeline=True)
    updated = projects.get(project_id)
    return project_meta_from_row(updated)


def complete_project(conn: Any, project_id: str, body: CompleteRequest) -> Intent:
    projects = ProjectRepository(conn)
    require_project_active(projects.get(project_id))
    LeaseRepository(conn).expire_reason_leases(project_id)
    validate_facts_exist(body.from_, projects.existing_fact_ids(project_id, body.from_))
    validate_goal_not_in_sources(body.from_)

    now = utcnow()
    intent_id = IdRepository(conn).next_intent_id(project_id)

    IntentRepository(conn).insert_completed_goal(
        project_id=project_id,
        intent_id=intent_id,
        source_fact_ids=body.from_,
        description=body.description,
        worker=body.worker,
        now=now,
    )
    ProjectRepository(conn).complete(project_id)
    ProjectRepository(conn).bump_revisions(project_id, graph=True, timeline=True)

    return Intent(
        id=intent_id,
        **{"from": body.from_},
        to="goal",
        description=body.description,
        creator=body.worker,
        worker=body.worker,
        last_heartbeat_at=now,
        created_at=now,
        concluded_at=now,
    )


def reopen_project(conn: Any, project_id: str, body: ReopenRequest) -> ReopenResponse:
    LeaseRepository(conn).expire_reason_leases(project_id)
    projects = ProjectRepository(conn)
    require_project_completed(projects.get(project_id))
    completion = completion_intent_or_409(projects.completion_intents(project_id))
    intents = IntentRepository(conn)

    source_ids = intents.source_fact_ids(project_id, completion["id"])
    if not source_ids:
        raise ConflictError("Completion intent is missing its source facts")

    now = utcnow()
    ids = IdRepository(conn)
    fact_id = ids.next_fact_id(project_id)
    intent_id = ids.next_intent_id(project_id)
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
    ReasonRepository(conn).clear_project_reason(project_id)
    updated_project = projects.reopen(project_id)
    projects.bump_revisions(project_id, graph=True, timeline=True)
    updated_project = projects.get(project_id)

    updated_intent = intents.get_intent(project_id, intent_id)
    assert updated_project is not None
    assert updated_intent is not None
    projection = intents.get_intent_projection(project_id, updated_intent["id"])
    assert projection is not None
    return ReopenResponse(
        project=project_meta_from_row(updated_project),
        fact=Fact(id=fact_id, description=description),
        intent=intent_to_model(projection),
    )
