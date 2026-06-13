from __future__ import annotations

from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.process import ProcessResult


def did_timeout(result: ProcessResult) -> bool:
    return not result.cancelled and (result.timed_out or result.returncode in (124, 137))


def cancel_reason(result: ProcessResult, cancellation: TaskCancellation | None = None) -> str | None:
    if result.cancelled:
        return result.cancel_reason or "cancelled"
    if cancellation is not None:
        return cancellation.reason
    return None


def process_state_for_task_outcome(outcome: str) -> str:
    if outcome == "success":
        return "completed"
    if outcome == "cancelled":
        return "cancelled"
    if outcome == "timeout":
        return "timeout"
    return "failed"
