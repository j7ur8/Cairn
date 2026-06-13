from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from cairn.server.domain.errors import BadRequestError, ConflictError, ForbiddenError

REASON_SUCCESS_OUTCOMES = {"success", "complete", "intents", "noop"}
REASON_FAILURE_OUTCOMES = {"failed", "timeout", "rejected", "unhealthy", "cancelled"}


@dataclass(slots=True)
class ReasonFinishState:
    trigger_hash: str
    outcome: str
    failure_count: int
    last_error: str
    next_retry_at: str | None


def reason_trigger_hash(trigger: str) -> str:
    return sha256(trigger.encode("utf-8")).hexdigest()


def check_reason_run_id_or_409(current_run_id: str | None, run_id: str | None) -> None:
    if current_run_id != run_id:
        raise ConflictError("Project reason run has been superseded")


def _current_run_id(row: Any) -> str | None:
    return row["reason_run_id"] if "reason_run_id" in row.keys() else None


def validate_reason_claimable(row: Any, worker: str, run_id: str | None = None) -> Any:
    if row["status"] != "active":
        raise ForbiddenError(f"Project is {row['status']}")
    current_worker = row["reason_worker"]
    if current_worker is not None:
        if current_worker != worker:
            raise ConflictError(f"Project reason is currently claimed by {current_worker}")
        check_reason_run_id_or_409(_current_run_id(row), run_id)
    return row


def claim_failed(row: Any, worker: str, run_id: str | None = None) -> None:
    validate_reason_claimable(row, worker, run_id)
    raise ConflictError("Project reason claim failed")


def validate_reason_heartbeatable(row: Any, worker: str, run_id: str | None = None) -> Any:
    if row["status"] != "active":
        raise ForbiddenError(f"Project is {row['status']}")
    current_worker = row["reason_worker"]
    if current_worker is None:
        raise ConflictError("Project reason is not currently claimed")
    if current_worker != worker:
        raise ConflictError(f"Project reason is currently claimed by {current_worker}")
    check_reason_run_id_or_409(_current_run_id(row), run_id)
    return row


def heartbeat_failed(row: Any, worker: str, run_id: str | None = None) -> None:
    validate_reason_heartbeatable(row, worker, run_id)
    raise ConflictError("Project reason heartbeat failed")


def validate_reason_releasable(row: Any, worker: str, run_id: str | None = None) -> Any:
    if row["status"] != "active":
        raise ForbiddenError(f"Project is {row['status']}")
    current_worker = row["reason_worker"]
    if current_worker is None:
        return row
    if current_worker != worker:
        raise ConflictError(f"Project reason is currently claimed by {current_worker}")
    check_reason_run_id_or_409(_current_run_id(row), run_id)
    return row


def release_failed(row: Any, worker: str, run_id: str | None = None) -> None:
    validate_reason_releasable(row, worker, run_id)
    raise ConflictError("Project reason release failed")


def validate_reason_finishable(row: Any, worker: str, run_id: str | None = None) -> Any:
    if row["status"] not in ("active", "completed", "stopped"):
        raise ForbiddenError(f"Project is {row['status']}")
    current_worker = row["reason_worker"]
    if row["status"] == "active" and current_worker is None:
        raise ConflictError("Project reason is not currently claimed")
    if row["status"] == "active" and current_worker is not None and current_worker != worker:
        raise ConflictError(f"Project reason is currently claimed by {current_worker}")
    if row["status"] == "active":
        check_reason_run_id_or_409(_current_run_id(row), run_id)
    return row


def finish_state(trigger: str, *, trigger_hash: str | None, outcome: str, error: str | None) -> ReasonFinishState:
    if outcome in REASON_FAILURE_OUTCOMES:
        failure_count = 1
        next_retry_at = None
    elif outcome in REASON_SUCCESS_OUTCOMES:
        failure_count = 0
        next_retry_at = None
    else:
        raise BadRequestError(f"invalid reason outcome: {outcome}")
    return ReasonFinishState(
        trigger_hash=trigger_hash or reason_trigger_hash(trigger),
        outcome=outcome,
        failure_count=failure_count,
        last_error=(error or "")[:4000],
        next_retry_at=next_retry_at,
    )


def should_clear_reason_after_finish(row: Any, worker: str) -> bool:
    return row["status"] == "active" and row["reason_worker"] == worker


_check_reason_run_id_or_409 = check_reason_run_id_or_409
