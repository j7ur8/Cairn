from __future__ import annotations

from fastapi import HTTPException

from cairn.server.config.files import load_dispatch_data, save_dispatch_data
from cairn.shared.contracts import BootstrapTaskTimeouts, ExploreTaskTimeouts, ReasonTaskTimeouts, TaskTimeouts


def get_task_timeouts() -> TaskTimeouts:
    data = load_dispatch_data()
    tasks = data.get("tasks")
    if not isinstance(tasks, dict):
        raise HTTPException(500, "dispatch.yaml tasks section missing")
    try:
        return TaskTimeouts(
            bootstrap=BootstrapTaskTimeouts(
                timeout=int(tasks["bootstrap"]["timeout"]),
                conclude_timeout=int(tasks["bootstrap"]["conclude_timeout"]),
            ),
            explore=ExploreTaskTimeouts(
                timeout=int(tasks["explore"]["timeout"]),
                conclude_timeout=int(tasks["explore"]["conclude_timeout"]),
            ),
            reason=ReasonTaskTimeouts(
                timeout=int(tasks["reason"]["timeout"]),
            ),
        )
    except (KeyError, TypeError) as exc:
        raise HTTPException(500, f"dispatch.yaml tasks missing or invalid: {exc}") from exc


def update_task_timeouts(body: TaskTimeouts) -> TaskTimeouts:
    data = load_dispatch_data()
    tasks = data.setdefault("tasks", {})
    if not isinstance(tasks, dict):
        raise HTTPException(500, "dispatch.yaml tasks must be a mapping")
    # Preserve reason.max_intents (not part of the timeouts contract) across the
    # overwrite below, falling back to the schema default when absent.
    reason_orig = tasks.get("reason")
    max_intents = 3
    if isinstance(reason_orig, dict) and "max_intents" in reason_orig:
        max_intents = reason_orig["max_intents"]
    tasks["bootstrap"] = {
        "timeout": body.bootstrap.timeout,
        "conclude_timeout": body.bootstrap.conclude_timeout,
    }
    tasks["explore"] = {
        "timeout": body.explore.timeout,
        "conclude_timeout": body.explore.conclude_timeout,
    }
    tasks["reason"] = {
        "timeout": body.reason.timeout,
        "max_intents": max_intents,
    }
    save_dispatch_data(data)
    return body
