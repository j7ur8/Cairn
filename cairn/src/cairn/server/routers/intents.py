from fastapi import APIRouter

from cairn.server import db
from cairn.server.models_pkg.intents import (
    ConcludeRequest,
    ConcludeResponse,
    CreateIntentRequest,
    HeartbeatRequest,
)
from cairn.server.models_pkg.projects import (
    Fact,
    Intent,
)
from cairn.server.repositories.intents import IntentRepository
from cairn.server.services import (
    claim_open_intent_or_409,
    check_project_active,
    conclude_open_intent_or_409,
    intent_to_model,
    next_fact_id,
    next_intent_id,
    release_open_intent_or_409,
    utcnow,
    validate_facts_exist,
    validate_intent_creator_worker,
    validate_goal_not_in_sources,
)

router = APIRouter(tags=["intents"])


@router.post(
    "/projects/{project_id}/intents",
    response_model=Intent,
    status_code=201,
)
def create_intent(project_id: str, body: CreateIntentRequest):
    with db.session_scope() as conn:
        check_project_active(conn, project_id)
        validate_facts_exist(conn, project_id, body.from_)
        validate_goal_not_in_sources(body.from_)
        validate_intent_creator_worker(body.creator, body.worker)

        now = utcnow()
        iid = next_intent_id(conn, project_id)
        claimed = body.worker is not None
        IntentRepository(conn).insert_open(
            project_id=project_id,
            intent_id=iid,
            source_fact_ids=body.from_,
            description=body.description,
            creator=body.creator,
            worker=body.worker,
            now=now,
        )

        return Intent(
            id=iid,
            **{"from": body.from_},
            to=None,
            description=body.description,
            creator=body.creator,
            worker=body.worker,
            last_heartbeat_at=now if claimed else None,
            created_at=now,
            concluded_at=None,
        )


@router.post(
    "/projects/{project_id}/intents/{intent_id}/heartbeat",
    response_model=Intent,
)
def heartbeat(project_id: str, intent_id: str, body: HeartbeatRequest):
    with db.session_scope() as conn:
        check_project_active(conn, project_id)

        now = utcnow()
        updated = claim_open_intent_or_409(conn, project_id, intent_id, body.worker, now)
        return intent_to_model(conn, updated, project_id)


@router.post(
    "/projects/{project_id}/intents/{intent_id}/release",
    response_model=Intent,
)
def release(project_id: str, intent_id: str, body: HeartbeatRequest):
    with db.session_scope() as conn:
        check_project_active(conn, project_id)
        row = release_open_intent_or_409(conn, project_id, intent_id, body.worker)
        return intent_to_model(conn, row, project_id)


@router.post(
    "/projects/{project_id}/intents/{intent_id}/conclude",
    response_model=ConcludeResponse,
)
def conclude(project_id: str, intent_id: str, body: ConcludeRequest):
    with db.session_scope() as conn:
        check_project_active(conn, project_id)

        now = utcnow()
        fid = next_fact_id(conn, project_id)

        IntentRepository(conn).insert_fact(project_id, fid, body.description)
        updated = conclude_open_intent_or_409(conn, project_id, intent_id, body.worker, fid, now)

        return ConcludeResponse(
            fact=Fact(id=fid, description=body.description),
            intent=intent_to_model(conn, updated, project_id),
        )
