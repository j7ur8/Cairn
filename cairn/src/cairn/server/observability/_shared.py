from __future__ import annotations

from typing import Any

from cairn.server.observability.models import LlmExecution, LlmExecutionEvent
from cairn.shared.contracts import normalize_llm_event_kinds


def normalize_event_kind_filter(
    event_kinds: list[str] | tuple[str, ...] | None,
) -> list[str] | None:
    if event_kinds is None:
        return None
    cleaned = [str(kind).strip() for kind in event_kinds]
    if not any(cleaned):
        return []
    return normalize_llm_event_kinds([kind for kind in cleaned if kind])


def row_to_execution(row: Any) -> LlmExecution:
    return LlmExecution(**dict(row))


def row_to_event(row: Any) -> LlmExecutionEvent:
    return LlmExecutionEvent(**dict(row))
