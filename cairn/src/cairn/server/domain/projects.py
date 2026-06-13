from __future__ import annotations

from typing import Any

from cairn.server.domain.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError


def require_project(row: Any | None) -> Any:
    if row is None:
        raise NotFoundError("Project not found")
    return row


def require_project_active(row: Any | None) -> Any:
    row = require_project(row)
    if row["status"] != "active":
        raise ForbiddenError(f"Project is {row['status']}")
    return row


def require_project_hint_writable(row: Any | None) -> Any:
    row = require_project(row)
    if row["status"] not in ("active", "stopped", "completed"):
        raise ForbiddenError(f"Project is {row['status']}")
    return row


def require_project_completed(row: Any | None) -> Any:
    row = require_project(row)
    if row["status"] != "completed":
        raise ForbiddenError(f"Project is {row['status']}")
    return row


def validate_facts_exist(fact_ids: list[str], existing_fact_ids: set[str]) -> None:
    for fact_id in fact_ids:
        if fact_id not in existing_fact_ids:
            raise NotFoundError(f"Fact {fact_id} not found")


def validate_goal_not_in_sources(fact_ids: list[str]) -> None:
    if "goal" in fact_ids:
        raise BadRequestError("goal cannot be used in from")


def completion_intent_or_409(rows: list[Any]) -> Any:
    if not rows:
        raise ConflictError("Completed project is missing its completion intent")
    if len(rows) != 1:
        raise ConflictError("Completed project has multiple completion intents")
    return rows[0]


def should_update_project_status(row: Any, requested_status: str) -> bool:
    current_status = row["status"]
    if current_status == "completed":
        raise ConflictError("Completed projects cannot change status")
    return current_status != requested_status
