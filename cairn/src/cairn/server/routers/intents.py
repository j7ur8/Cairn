from fastapi import APIRouter

from cairn.server import db
from cairn.server.application.intent_commands import (
    claim_intent,
    conclude_intent,
    heartbeat_intent,
    release_intent,
)
from cairn.server.application.intent_commands import (
    create_intent as create_intent_command,
)
from cairn.server.application.intent_phase_checkpoints import (
    clear_intent_phase_checkpoint,
    mark_intent_phase_checkpoint_failed,
    upsert_intent_phase_checkpoint,
)
from cairn.server.schemas import (
    ConcludeRequest,
    ConcludeResponse,
    CreateIntentRequest,
    HeartbeatRequest,
    IntentPhaseCheckpointFailedRequest,
    IntentPhaseCheckpointResponse,
    IntentPhaseCheckpointUpsertRequest,
)
from cairn.shared.contracts import Intent

router = APIRouter(tags=["intents"])


@router.post(
    "/projects/{project_id}/intents",
    response_model=Intent,
    status_code=201,
)
def create_intent(project_id: str, body: CreateIntentRequest):
    with db.session_scope() as conn:
        return create_intent_command(conn, project_id, body)


@router.post(
    "/projects/{project_id}/intents/{intent_id}/claim",
    response_model=Intent,
)
def claim(project_id: str, intent_id: str, body: HeartbeatRequest):
    with db.session_scope() as conn:
        return claim_intent(conn, project_id, intent_id, body)


@router.post(
    "/projects/{project_id}/intents/{intent_id}/heartbeat",
    response_model=Intent,
)
def heartbeat(project_id: str, intent_id: str, body: HeartbeatRequest):
    with db.session_scope() as conn:
        return heartbeat_intent(conn, project_id, intent_id, body)


@router.post(
    "/projects/{project_id}/intents/{intent_id}/release",
    response_model=Intent,
)
def release(project_id: str, intent_id: str, body: HeartbeatRequest):
    with db.session_scope() as conn:
        return release_intent(conn, project_id, intent_id, body)


@router.post(
    "/projects/{project_id}/intents/{intent_id}/conclude",
    response_model=ConcludeResponse,
)
def conclude(project_id: str, intent_id: str, body: ConcludeRequest):
    with db.session_scope() as conn:
        return conclude_intent(conn, project_id, intent_id, body)


@router.put(
    "/projects/{project_id}/intents/{intent_id}/phase-checkpoints/{phase}",
    response_model=IntentPhaseCheckpointResponse,
)
def upsert_phase_checkpoint(project_id: str, intent_id: str, phase: str, body: IntentPhaseCheckpointUpsertRequest):
    with db.session_scope() as conn:
        return upsert_intent_phase_checkpoint(conn, project_id, intent_id, phase, body)


@router.post(
    "/projects/{project_id}/intents/{intent_id}/phase-checkpoints/{phase}/failed",
    response_model=IntentPhaseCheckpointResponse,
)
def mark_phase_checkpoint_failed(project_id: str, intent_id: str, phase: str, body: IntentPhaseCheckpointFailedRequest):
    with db.session_scope() as conn:
        return mark_intent_phase_checkpoint_failed(conn, project_id, intent_id, phase, body)


@router.delete(
    "/projects/{project_id}/intents/{intent_id}/phase-checkpoints/{phase}",
    response_model=IntentPhaseCheckpointResponse,
)
def clear_phase_checkpoint(project_id: str, intent_id: str, phase: str):
    with db.session_scope() as conn:
        return clear_intent_phase_checkpoint(conn, project_id, intent_id, phase)
