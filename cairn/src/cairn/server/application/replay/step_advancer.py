from __future__ import annotations

from typing import Any

from cairn.server.application.replay.constants import _REPLAY_CREATOR
from cairn.server.application.replay.route_extractor import intent_source_ids
from cairn.server.domain.errors import ConflictError
from cairn.server.domain.projects import completion_intent_or_409
from cairn.server.domain.time import utcnow
from cairn.server.models_pkg.projects import Intent
from cairn.server.repositories.ids import IdRepository
from cairn.server.repositories.intents import IntentRepository
from cairn.server.repositories.projects import ProjectRepository
from cairn.server.repositories.replay import ReplayRepository


def replay_steps(conn: Any, run_id: str) -> list[Any]:
    return ReplayRepository(conn).steps(run_id)


def sync_concluded_steps(conn: Any, run: Any) -> None:
    now = utcnow()
    repo = ReplayRepository(conn)
    steps = repo.created_steps_with_replay_intent(run["id"])
    for step in steps:
        replay_intent = repo.get_intent(run["replay_project_id"], step["replay_intent_id"])
        if replay_intent is None or replay_intent["to_fact_id"] is None or replay_intent["concluded_at"] is None:
            continue
        repo.map_fact(
            run_id=run["id"],
            source_fact_id=step["source_to_fact_id"],
            replay_fact_id=replay_intent["to_fact_id"],
        )
        repo.mark_step_concluded(run_id=run["id"], step_index=step["step_index"], concluded_at=now)


def create_replay_intent(conn: Any, run: Any, step: Any) -> Intent | str:
    replay_repo = ReplayRepository(conn)
    intent_repo = IntentRepository(conn)
    source_intent = replay_repo.get_intent(run["source_project_id"], step["source_intent_id"])
    if source_intent is None:
        return f"Source intent {step['source_intent_id']} not found"

    mapped_sources: list[str] = []
    for source_fact_id in intent_source_ids(conn, run["source_project_id"], source_intent["id"]):
        mapped = mapped_fact_id(conn, run["id"], source_fact_id)
        if mapped is None:
            return f"Source fact {source_fact_id} is not mapped yet"
        mapped_sources.append(mapped)

    expected_description = replay_repo.fact_description(run["source_project_id"], step["source_to_fact_id"])
    description = replay_intent_description(source_intent, step["source_to_fact_id"], expected_description)
    now = utcnow()
    intent_id = IdRepository(conn).next_intent_id(run["replay_project_id"])
    intent_repo.insert_open(
        project_id=run["replay_project_id"],
        intent_id=intent_id,
        source_fact_ids=mapped_sources,
        description=description,
        creator=_REPLAY_CREATOR,
        worker=None,
        now=now,
    )
    replay_repo.mark_step_created(
        run_id=run["id"],
        step_index=step["step_index"],
        replay_intent_id=intent_id,
        created_at=now,
    )
    return Intent(
        id=intent_id,
        **{"from": mapped_sources},
        to=None,
        description=description,
        creator=_REPLAY_CREATOR,
        worker=None,
        last_heartbeat_at=None,
        created_at=now,
        concluded_at=None,
    )


def mapped_fact_id(conn: Any, run_id: str, source_fact_id: str) -> str | None:
    return ReplayRepository(conn).mapped_fact_id(run_id, source_fact_id)


def replay_intent_description(source_intent: Any, source_to_fact_id: str, expected_description: str) -> str:
    parts = [
        f"Replay original intent {source_intent['id']} and reproduce its decisive result.",
        "",
        "Original task:",
        source_intent["description"],
        "",
        f"Expected source fact: {source_to_fact_id}",
    ]
    if expected_description:
        parts.extend(["Expected result to reproduce:", expected_description])
    parts.append("Do not simply restate the expected result; rerun the necessary commands and report the reproduced evidence.")
    return "\n".join(parts)


def complete_replay_project(conn: Any, run: Any) -> Any | None:
    projects = ProjectRepository(conn)
    intents = IntentRepository(conn)
    replay_repo = ReplayRepository(conn)
    existing = projects.completion_intents(run["replay_project_id"])
    if len(existing) == 1:
        mark_run_completed(conn, run["id"])
        return existing[0]
    if len(existing) > 1:
        raise ConflictError("Replay project has multiple completion intents")

    source_completion = completion_intent_or_409(ProjectRepository(conn).completion_intents(run["source_project_id"]))
    mapped_sources: list[str] = []
    for source_fact_id in intent_source_ids(conn, run["source_project_id"], source_completion["id"]):
        mapped = mapped_fact_id(conn, run["id"], source_fact_id)
        if mapped is None:
            raise ConflictError(f"Completion source fact {source_fact_id} is not mapped")
        mapped_sources.append(mapped)

    now = utcnow()
    intent_id = IdRepository(conn).next_intent_id(run["replay_project_id"])
    intents.insert_completed_goal(
        project_id=run["replay_project_id"],
        intent_id=intent_id,
        source_fact_ids=mapped_sources,
        description=run["completion_description"],
        worker=_REPLAY_CREATOR,
        now=now,
    )
    projects.complete(run["replay_project_id"])
    mark_run_completed(conn, run["id"])
    return replay_repo.get_intent(run["replay_project_id"], intent_id)


def mark_run_completed(conn: Any, run_id: str) -> None:
    ReplayRepository(conn).mark_run_completed(run_id, utcnow())
