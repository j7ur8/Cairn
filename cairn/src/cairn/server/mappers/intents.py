from __future__ import annotations

from typing import Any

from cairn.shared.contracts import Intent


def intent_to_model(row: Any) -> Intent:
    return Intent(
        id=row["id"],
        **{"from": list(row["from"])},
        to=row["to_fact_id"],
        description=row["description"],
        creator=row["creator"],
        worker=row["worker"],
        last_heartbeat_at=row["last_heartbeat_at"],
        created_at=row["created_at"],
        concluded_at=row["concluded_at"],
        priority_score=row["priority_score"],
        intent_kind=row["intent_kind"],
        tags=list(row["tags"]),
        score_reason=row["score_reason"],
    )


def build_intents(rows: list[Any]) -> list[Intent]:
    return [intent_to_model(row) for row in rows]
