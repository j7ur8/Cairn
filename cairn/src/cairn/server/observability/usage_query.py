from __future__ import annotations

import json
from typing import Any

from cairn.server.observability.models import LlmUsageActivity
from cairn.server.observability.usage_repository import LlmUsageRepository


def latest_usage_activity(
    conn: Any,
    where_sql: str,
    params: dict[str, object],
) -> LlmUsageActivity | None:
    row, usage_count = LlmUsageRepository(conn).latest_usage_activity_for_where(where_sql, params)
    return activity_from_usage_row(row, usage_count)


def activity_from_usage_row(row: Any | None, usage_count: int) -> LlmUsageActivity | None:
    if usage_count <= 0:
        return None
    if row is None:
        return None
    payload = _parse_json_object(str(row["content"] or ""))
    subtype = payload.get("subtype") if isinstance(payload.get("subtype"), str) else None
    tokens = _optional_int(
        payload.get("estimated_tokens")
        if payload.get("estimated_tokens") is not None
        else payload.get("thinking_tokens")
        if payload.get("thinking_tokens") is not None
        else payload.get("output_tokens")
        if payload.get("output_tokens") is not None
        else payload.get("input_tokens")
    )
    return LlmUsageActivity(
        latest_usage_sequence=int(row["sequence"]),
        latest_usage_at=str(row["created_at"]),
        subtype=subtype,
        tokens=tokens,
        delta=_optional_int(payload.get("estimated_tokens_delta")),
        hidden_usage_count=usage_count,
    )


def _parse_json_object(value: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)  # type: ignore[call-overload]  # except guards non-convertible input
    except (TypeError, ValueError):
        return None
