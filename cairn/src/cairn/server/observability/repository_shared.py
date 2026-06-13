from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IncrementalEventRows:
    rows: list[Any]
    last_sequence: int


@dataclass(frozen=True)
class EventViewRows:
    rows: list[Any]
    last_sequence: int
    by_kind: dict[str, int]
    usage_row: Any | None
    usage_count: int


def base_event_filter(
    project_id: str,
    *,
    execution_id: str | None,
    after: int | None,
) -> tuple[list[str], dict[str, object]]:
    where = ["project_id = :project_id"]
    params: dict[str, object] = {"project_id": project_id}
    if execution_id:
        where.append("execution_id = :execution_id")
        params["execution_id"] = execution_id
    if after is not None:
        where.append("sequence > :after")
        params["after"] = after
    return where, params


def append_event_kind_filter(
    where: list[str],
    params: dict[str, object],
    event_kinds: list[str] | None,
) -> None:
    if event_kinds is None:
        return
    placeholders: list[str] = []
    for index, kind in enumerate(event_kinds):
        key = f"event_kind_{index}"
        placeholders.append(f":{key}")
        params[key] = kind
    where.append(f"event_kind IN ({', '.join(placeholders)})")
