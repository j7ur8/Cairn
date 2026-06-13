from __future__ import annotations

from typing import Any

from cairn.server.domain.intents import (
    claim_failed,
    conclude_failed,
    heartbeat_failed,
    release_failed,
    validate_claim_result,
    validate_claimable_open_intent,
    validate_conclude_result,
    validate_heartbeatable_open_intent,
    validate_intent_creator_worker,
    validate_releasable_open_intent,
)
from cairn.server.domain.projects import (
    require_project_active,
    validate_facts_exist,
    validate_goal_not_in_sources,
)
from cairn.server.domain.time import utcnow
from cairn.server.mappers.intents import intent_to_model
from cairn.server.models_pkg import (
    ConcludeRequest,
    ConcludeResponse,
    CreateIntentRequest,
    HeartbeatRequest,
)
from cairn.server.models_pkg.projects import Fact, Intent
from cairn.server.repositories.ids import IdRepository
from cairn.server.repositories.intents import IntentRepository
from cairn.server.repositories.leases import LeaseRepository
from cairn.server.repositories.projects import ProjectRepository


def create_intent(conn: Any, project_id: str, body: CreateIntentRequest) -> Intent:
    projects = ProjectRepository(conn)
    require_project_active(projects.get(project_id))
    validate_facts_exist(body.from_, projects.existing_fact_ids(project_id, body.from_))
    validate_goal_not_in_sources(body.from_)
    validate_intent_creator_worker(body.creator, body.worker)

    now = utcnow()
    intent_id = IdRepository(conn).next_intent_id(project_id)
    claimed = body.worker is not None
    IntentRepository(conn).insert_open(
        project_id=project_id,
        intent_id=intent_id,
        source_fact_ids=body.from_,
        description=body.description,
        creator=body.creator,
        worker=body.worker,
        now=now,
    )

    return Intent(
        id=intent_id,
        **{"from": body.from_},
        to=None,
        description=body.description,
        creator=body.creator,
        worker=body.worker,
        last_heartbeat_at=now if claimed else None,
        created_at=now,
        concluded_at=None,
    )


def claim_intent(conn: Any, project_id: str, intent_id: str, body: HeartbeatRequest) -> Intent:
    require_project_active(ProjectRepository(conn).get(project_id))
    LeaseRepository(conn).expire_workers(project_id)
    now = utcnow()
    intents = IntentRepository(conn)
    validate_claimable_open_intent(intents.get_intent(project_id, intent_id), body.worker)
    if intents.claim_open(project_id, intent_id, body.worker, now) != 1:
        claim_failed(intents.get_intent(project_id, intent_id), body.worker)
    updated = validate_claim_result(intents.get_intent(project_id, intent_id), body.worker)
    projection = intents.get_intent_projection(project_id, updated["id"])
    assert projection is not None
    return intent_to_model(projection)


def heartbeat_intent(conn: Any, project_id: str, intent_id: str, body: HeartbeatRequest) -> Intent:
    require_project_active(ProjectRepository(conn).get(project_id))
    LeaseRepository(conn).expire_workers(project_id)
    now = utcnow()
    intents = IntentRepository(conn)
    validate_heartbeatable_open_intent(intents.get_intent(project_id, intent_id), body.worker)
    if intents.heartbeat_open(project_id, intent_id, body.worker, now) != 1:
        heartbeat_failed(intents.get_intent(project_id, intent_id), body.worker)
    updated = validate_heartbeatable_open_intent(intents.get_intent(project_id, intent_id), body.worker)
    projection = intents.get_intent_projection(project_id, updated["id"])
    assert projection is not None
    return intent_to_model(projection)


def release_intent(conn: Any, project_id: str, intent_id: str, body: HeartbeatRequest) -> Intent:
    require_project_active(ProjectRepository(conn).get(project_id))
    LeaseRepository(conn).expire_workers(project_id)
    intents = IntentRepository(conn)
    row = validate_releasable_open_intent(intents.get_intent(project_id, intent_id), body.worker)
    if row["worker"] is not None:
        if intents.release_open(project_id, intent_id, body.worker) != 1:
            release_failed(intents.get_intent(project_id, intent_id), body.worker)
        row = intents.get_intent(project_id, intent_id)
    projection = intents.get_intent_projection(project_id, row["id"])
    assert projection is not None
    return intent_to_model(projection)


def conclude_intent(conn: Any, project_id: str, intent_id: str, body: ConcludeRequest) -> ConcludeResponse:
    require_project_active(ProjectRepository(conn).get(project_id))
    LeaseRepository(conn).expire_workers(project_id)
    intents = IntentRepository(conn)
    validate_heartbeatable_open_intent(intents.get_intent(project_id, intent_id), body.worker)

    now = utcnow()
    fact_id = IdRepository(conn).next_fact_id(project_id)

    intents.insert_fact(project_id, fact_id, body.description)
    if intents.conclude_open(project_id, intent_id, body.worker, fact_id, now) != 1:
        conclude_failed(intents.get_intent(project_id, intent_id), body.worker)
    updated = validate_conclude_result(intents.get_intent(project_id, intent_id), body.worker, fact_id)

    projection = intents.get_intent_projection(project_id, updated["id"])
    assert projection is not None
    return ConcludeResponse(
        fact=Fact(id=fact_id, description=body.description),
        intent=intent_to_model(projection),
    )
