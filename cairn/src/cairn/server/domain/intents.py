from __future__ import annotations

from typing import Any

from cairn.server.domain.errors import BadRequestError, ConflictError, NotFoundError


def validate_intent_creator_worker(creator: str, worker: str | None) -> None:
    if worker is not None and worker != creator:
        raise BadRequestError("worker must be null or equal to creator")


def require_intent(row: Any | None) -> Any:
    if row is None:
        raise NotFoundError("Intent not found")
    return row


def validate_claimable_open_intent(row: Any | None, worker: str) -> Any:
    row = require_intent(row)
    if row["to_fact_id"] is not None:
        raise ConflictError("Intent already concluded")
    if row["worker"] is not None and row["worker"] != worker:
        raise ConflictError(f"Intent is currently claimed by {row['worker']}")
    return row


def validate_claim_result(row: Any | None, worker: str) -> Any:
    row = validate_claimable_open_intent(row, worker)
    if row["worker"] != worker:
        raise ConflictError("Intent claim failed")
    return row


def claim_failed(row: Any | None, worker: str) -> None:
    validate_claimable_open_intent(row, worker)
    raise ConflictError("Intent claim failed")


def validate_heartbeatable_open_intent(row: Any | None, worker: str) -> Any:
    row = require_intent(row)
    if row["to_fact_id"] is not None:
        raise ConflictError("Intent already concluded")
    if row["worker"] is None:
        raise ConflictError("Intent is not currently claimed")
    if row["worker"] != worker:
        raise ConflictError(f"Intent is currently claimed by {row['worker']}")
    return row


def heartbeat_failed(row: Any | None, worker: str) -> None:
    validate_heartbeatable_open_intent(row, worker)
    raise ConflictError("Intent heartbeat failed")


def validate_releasable_open_intent(row: Any | None, worker: str) -> Any:
    row = require_intent(row)
    if row["to_fact_id"] is not None:
        raise ConflictError("Intent already concluded")
    if row["worker"] is None:
        return row
    if row["worker"] != worker:
        raise ConflictError(f"Intent is currently claimed by {row['worker']}")
    return row


def release_failed(row: Any | None, worker: str) -> None:
    validate_releasable_open_intent(row, worker)
    raise ConflictError("Intent release failed")


def validate_conclude_result(row: Any | None, worker: str, fact_id: str) -> Any:
    row = require_intent(row)
    if row["to_fact_id"] != fact_id or row["worker"] != worker:
        raise ConflictError("Intent conclude failed")
    return row


def conclude_failed(row: Any | None, worker: str) -> None:
    validate_claimable_open_intent(row, worker)
    raise ConflictError("Intent conclude failed")
