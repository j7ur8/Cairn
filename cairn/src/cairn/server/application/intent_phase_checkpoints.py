from __future__ import annotations

from typing import Any

from cairn.server.domain.errors import BadRequestError
from cairn.server.domain.intents import require_intent
from cairn.server.domain.projects import require_project_active
from cairn.server.domain.time import utcnow
from cairn.server.repositories.intent_phase_checkpoints import (
    EXPLORE_CONCLUDE_PHASE,
    IntentPhaseCheckpointRepository,
)
from cairn.server.repositories.intents import IntentRepository
from cairn.server.repositories.projects import ProjectRepository
from cairn.server.schemas import (
    IntentPhaseCheckpointFailedRequest,
    IntentPhaseCheckpointResponse,
    IntentPhaseCheckpointUpsertRequest,
)
from cairn.shared.contracts import IntentPhaseCheckpoint


def _validate_phase(phase: str) -> None:
    if phase != EXPLORE_CONCLUDE_PHASE:
        raise BadRequestError("unsupported checkpoint phase")


def _checkpoint_model(row: Any | None) -> IntentPhaseCheckpoint | None:
    if row is None:
        return None
    return IntentPhaseCheckpoint(
        project_id=row["project_id"],
        intent_id=row["intent_id"],
        phase=row["phase"],
        worker_name=row["worker_name"],
        worker_type=row["worker_type"],
        session_id=row["session_id"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def upsert_intent_phase_checkpoint(
    conn: Any,
    project_id: str,
    intent_id: str,
    phase: str,
    body: IntentPhaseCheckpointUpsertRequest,
) -> IntentPhaseCheckpointResponse:
    _validate_phase(phase)
    require_project_active(ProjectRepository(conn).get(project_id))
    require_intent(IntentRepository(conn).get_intent(project_id, intent_id))
    row = IntentPhaseCheckpointRepository(conn).upsert(
        project_id=project_id,
        intent_id=intent_id,
        phase=phase,
        worker_name=body.worker_name,
        worker_type=body.worker_type,
        session_id=body.session_id,
        now=utcnow(),
    )
    return IntentPhaseCheckpointResponse(checkpoint=_checkpoint_model(row))


def mark_intent_phase_checkpoint_failed(
    conn: Any,
    project_id: str,
    intent_id: str,
    phase: str,
    body: IntentPhaseCheckpointFailedRequest,
) -> IntentPhaseCheckpointResponse:
    _validate_phase(phase)
    require_project_active(ProjectRepository(conn).get(project_id))
    require_intent(IntentRepository(conn).get_intent(project_id, intent_id))
    row = IntentPhaseCheckpointRepository(conn).mark_failed(
        project_id=project_id,
        intent_id=intent_id,
        phase=phase,
        last_error=body.last_error,
        now=utcnow(),
    )
    return IntentPhaseCheckpointResponse(checkpoint=_checkpoint_model(row))


def clear_intent_phase_checkpoint(
    conn: Any,
    project_id: str,
    intent_id: str,
    phase: str,
) -> IntentPhaseCheckpointResponse:
    _validate_phase(phase)
    require_project_active(ProjectRepository(conn).get(project_id))
    require_intent(IntentRepository(conn).get_intent(project_id, intent_id))
    IntentPhaseCheckpointRepository(conn).clear(project_id, intent_id, phase)
    return IntentPhaseCheckpointResponse(checkpoint=None)
