from __future__ import annotations

from typing import Any

from cairn.server.domain.errors import ConflictError
from cairn.server.repositories.replay import ReplayRepository


def intent_source_ids(conn: Any, project_id: str, intent_id: str) -> list[str]:
    from cairn.server.repositories.intents import IntentRepository

    return IntentRepository(conn).source_fact_ids(project_id, intent_id)


def extract_replay_route(conn: Any, project_id: str, completion_source_ids: list[str]) -> list[Any]:
    replay_repo = ReplayRepository(conn)
    _, sources_by_intent, producers_by_fact = replay_repo.route_graph_for_facts(project_id, completion_source_ids)
    route: list[Any] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit_fact(fact_id: str) -> None:
        if fact_id in ("origin", "goal"):
            return
        rows = producers_by_fact.get(fact_id, [])
        if not rows:
            raise ConflictError(f"Fact {fact_id} has no producing intent")
        if len(rows) > 1:
            raise ConflictError(f"Fact {fact_id} has multiple producing intents")
        visit_intent(rows[0])

    def visit_intent(intent: Any) -> None:
        intent_id = intent["id"]
        if intent_id in visited:
            return
        if intent_id in visiting:
            raise ConflictError("Replay route contains a cycle")
        if intent["to_fact_id"] == "goal":
            return
        visiting.add(intent_id)
        for source_id in sources_by_intent.get(intent_id, []):
            visit_fact(source_id)
        visiting.remove(intent_id)
        visited.add(intent_id)
        route.append(intent)

    for source_id in completion_source_ids:
        visit_fact(source_id)
    return route
