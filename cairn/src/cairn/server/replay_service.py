from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import HTTPException

from cairn.server import db
from cairn.server.models_pkg.projects import (
    Fact,
    Hint,
    Intent,
    ProjectDetail,
    CreateHintInline,
    hidden_kinds_from_visible,
    parse_llm_hidden_event_kinds,
)
from cairn.server.models_pkg.intents import (
    ReplayRunAdvanceResponse,
    ReplayRunCreateRequest,
    ReplayRunCreateResponse,
)
from cairn.server.execution_config_service import execution_capabilities, load_worker_execution_configs
from cairn.server.models_pkg.capabilities import CapabilitySelection
from cairn.server.project_creation_service import ProjectCreationDraft, create_project_from_draft
from cairn.server.repositories import sql
from cairn.server.services import (
    build_intents,
    check_project_completed,
    get_completion_intent_or_409,
    get_project_or_404,
    next_intent_id,
    next_project_id,
    project_meta_from_row,
    utcnow,
)

_REPLAY_CREATOR = "dispatcher.replay"


def _attachments_root() -> Path:
    from cairn.server.runtime_config import system_config
    return Path(system_config().paths.resolved_attachments_root)


def create_replay_run(project_id: str, body: ReplayRunCreateRequest):
    replay_project_id: str | None = None
    run_id: str | None = None
    with db.session_scope() as conn:
        check_project_completed(conn, project_id)
        completion = get_completion_intent_or_409(conn, project_id)
        completion_source_ids = _intent_source_ids(conn, project_id, completion["id"])
        if not completion_source_ids:
            raise HTTPException(409, "Completed project is missing completion source facts")

        route = _extract_replay_route(conn, project_id, completion_source_ids)
        if not route:
            raise HTTPException(409, "Completed project has no replayable worker route")

        now = utcnow()
        replay_project_id = next_project_id(conn)
        run_id = f"replay_{replay_project_id}"
        source_project = get_project_or_404(conn, project_id)
        llm_hidden_event_kinds = (
            hidden_kinds_from_visible(body.llm_visible_event_kinds)
            if body.llm_visible_event_kinds is not None
            else parse_llm_hidden_event_kinds(
                source_project["llm_hidden_event_kinds"]
                if "llm_hidden_event_kinds" in source_project.keys()
                else None
            )
        )

        replay_capabilities = body.capabilities
        if body.capabilities is None:
            replay_capabilities = {
                task: CapabilitySelection(
                    mcp_server_ids=list(selection.user_mcp_server_ids or []),
                    skill_ids=list(selection.user_skill_ids or []),
                )
                for task, selection in execution_capabilities(
                    load_worker_execution_configs(conn, project_id)
                ).items()
            }
        rewritten_hints = [
            CreateHintInline(
                content=_rewrite_attachment_refs(hint.content, project_id, replay_project_id),
                creator=hint.creator,
            )
            for hint in body.hints or []
        ]
        create_project_from_draft(
            conn,
            ProjectCreationDraft(
                project_id=replay_project_id,
                title=body.title,
                origin=body.origin,
                goal=body.goal,
                hints=rewritten_hints,
                capabilities=replay_capabilities,
                ai_profiles=body.ai_profiles,
                task_timeouts=body.task_timeouts,
                role_id=body.role_id,
                llm_hidden_event_kinds=llm_hidden_event_kinds,
                status="stopped",
            ),
        )
        sql.execute(
            conn,
            """
            INSERT INTO replay_runs (
                id, source_project_id, replay_project_id, status,
                completion_description, created_at
            ) VALUES (
                :id, :source_project_id, :replay_project_id, 'active',
                :completion_description, :created_at
            )
            """,
            {
                "id": run_id,
                "source_project_id": project_id,
                "replay_project_id": replay_project_id,
                "completion_description": completion["description"],
                "created_at": now,
            },
        )
        sql.execute(
            conn,
            """
            INSERT INTO replay_fact_map (run_id, source_fact_id, replay_fact_id)
            VALUES (:run_id, 'origin', 'origin')
            """,
            {"run_id": run_id},
        )
        sql.execute(
            conn,
            """
            INSERT INTO replay_fact_map (run_id, source_fact_id, replay_fact_id)
            VALUES (:run_id, 'goal', 'goal')
            """,
            {"run_id": run_id},
        )
        for index, source_intent in enumerate(route):
            sql.execute(
                conn,
                """
                INSERT INTO replay_steps (
                    run_id, step_index, source_intent_id, source_to_fact_id, status
                ) VALUES (
                    :run_id, :step_index, :source_intent_id, :source_to_fact_id, 'pending'
                )
                """,
                {
                    "run_id": run_id,
                    "step_index": index,
                    "source_intent_id": source_intent["id"],
                    "source_to_fact_id": source_intent["to_fact_id"],
                },
            )

    try:
        _copy_project_attachments(project_id, replay_project_id)
        with db.session_scope() as conn:
            sql.execute(
                conn,
                "UPDATE projects SET status = 'active' WHERE id = :project_id",
                {"project_id": replay_project_id},
            )
            detail = _project_detail(conn, replay_project_id)
            return ReplayRunCreateResponse(
                run_id=run_id,
                source_project_id=project_id,
                project=detail,
            )
    except Exception:
        if replay_project_id:
            shutil.rmtree(_attachments_root() / replay_project_id, ignore_errors=True)
            with db.session_scope() as conn:
                sql.execute(
                    conn,
                    "DELETE FROM projects WHERE id = :project_id",
                    {"project_id": replay_project_id},
                )
        raise


def advance_replay_run(project_id: str):
    with db.session_scope() as conn:
        run = sql.fetchone(
            conn,
            """
            SELECT *
            FROM replay_runs
            WHERE replay_project_id = :project_id
            """,
            {"project_id": project_id},
        )
        if run is None:
            return ReplayRunAdvanceResponse(is_replay=False, action="not_replay", status="not_replay")

        replay_project = get_project_or_404(conn, project_id)
        if replay_project["status"] == "completed" or run["status"] == "completed":
            _mark_run_completed(conn, run["id"])
            return ReplayRunAdvanceResponse(
                is_replay=True,
                action="completed",
                status="completed",
                run_id=run["id"],
                project_id=project_id,
            )
        if replay_project["status"] != "active":
            return ReplayRunAdvanceResponse(
                is_replay=True,
                action="blocked",
                status="blocked",
                run_id=run["id"],
                project_id=project_id,
                detail=f"Replay project is {replay_project['status']}",
            )

        _sync_concluded_steps(conn, run)
        steps = _replay_steps(conn, run["id"])
        active_step = next((step for step in steps if step["status"] == "created"), None)
        if active_step is not None:
            return ReplayRunAdvanceResponse(
                is_replay=True,
                action="waiting",
                status="active",
                run_id=run["id"],
                project_id=project_id,
                intent_id=active_step["replay_intent_id"],
            )

        pending_step = next((step for step in steps if step["status"] == "pending"), None)
        if pending_step is None:
            completed = _complete_replay_project(conn, run)
            return ReplayRunAdvanceResponse(
                is_replay=True,
                action="completed",
                status="completed",
                run_id=run["id"],
                project_id=project_id,
                intent_id=completed["id"] if completed is not None else None,
            )

        created = _create_replay_intent(conn, run, pending_step)
        if isinstance(created, str):
            return ReplayRunAdvanceResponse(
                is_replay=True,
                action="blocked",
                status="blocked",
                run_id=run["id"],
                project_id=project_id,
                detail=created,
            )
        return ReplayRunAdvanceResponse(
            is_replay=True,
            action="created_intent",
            status="active",
            run_id=run["id"],
            project_id=project_id,
            intent_id=created.id,
        )


def _project_detail(conn, project_id: str) -> ProjectDetail:
    row = get_project_or_404(conn, project_id)
    facts = sql.fetchall(conn, "SELECT * FROM facts WHERE project_id = :project_id", {"project_id": project_id})
    hints = sql.fetchall(
        conn,
        "SELECT * FROM hints WHERE project_id = :project_id ORDER BY created_at",
        {"project_id": project_id},
    )
    return ProjectDetail(
        project=project_meta_from_row(row),
        facts=[Fact(**dict(fact)) for fact in facts],
        intents=build_intents(conn, project_id),
        hints=[Hint(**dict(hint)) for hint in hints],
    )


def _intent_source_ids(conn, project_id: str, intent_id: str) -> list[str]:
    rows = sql.fetchall(
        conn,
        """
        SELECT fact_id
        FROM intent_sources
        WHERE intent_id = :intent_id AND project_id = :project_id
        ORDER BY position, fact_id
        """,
        {"intent_id": intent_id, "project_id": project_id},
    )
    return [row["fact_id"] for row in rows]


def _extract_replay_route(conn, project_id: str, completion_source_ids: list[str]):
    route = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit_fact(fact_id: str) -> None:
        if fact_id in ("origin", "goal"):
            return
        rows = sql.fetchall(
            conn,
            """
            SELECT *
            FROM intents
            WHERE project_id = :project_id AND to_fact_id = :fact_id
            """,
            {"project_id": project_id, "fact_id": fact_id},
        )
        if not rows:
            raise HTTPException(409, f"Fact {fact_id} has no producing intent")
        if len(rows) > 1:
            raise HTTPException(409, f"Fact {fact_id} has multiple producing intents")
        visit_intent(rows[0])

    def visit_intent(intent) -> None:
        intent_id = intent["id"]
        if intent_id in visited:
            return
        if intent_id in visiting:
            raise HTTPException(409, "Replay route contains a cycle")
        if intent["to_fact_id"] == "goal":
            return
        visiting.add(intent_id)
        for source_id in _intent_source_ids(conn, project_id, intent_id):
            visit_fact(source_id)
        visiting.remove(intent_id)
        visited.add(intent_id)
        route.append(intent)

    for source_id in completion_source_ids:
        visit_fact(source_id)
    return route


def _copy_project_attachments(source_project_id: str, replay_project_id: str) -> Path | None:
    source = _attachments_root() / source_project_id
    if not source.exists() or not source.is_dir():
        return None
    target = _attachments_root() / replay_project_id
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


def _rewrite_attachment_refs(text: str, source_project_id: str, replay_project_id: str) -> str:
    return text.replace(
        f"/mnt/attachments/{source_project_id}",
        f"/mnt/attachments/{replay_project_id}",
    )


def _replay_steps(conn, run_id: str):
    return sql.fetchall(
        conn,
        """
        SELECT *
        FROM replay_steps
        WHERE run_id = :run_id
        ORDER BY step_index
        """,
        {"run_id": run_id},
    )


def _sync_concluded_steps(conn, run) -> None:
    now = utcnow()
    steps = sql.fetchall(
        conn,
        """
        SELECT *
        FROM replay_steps
        WHERE run_id = :run_id AND status = 'created' AND replay_intent_id IS NOT NULL
        ORDER BY step_index
        """,
        {"run_id": run["id"]},
    )
    for step in steps:
        replay_intent = sql.fetchone(
            conn,
            "SELECT * FROM intents WHERE project_id = :project_id AND id = :intent_id",
            {"project_id": run["replay_project_id"], "intent_id": step["replay_intent_id"]},
        )
        if replay_intent is None or replay_intent["to_fact_id"] is None or replay_intent["concluded_at"] is None:
            continue
        sql.execute(
            conn,
            """
            INSERT INTO replay_fact_map (run_id, source_fact_id, replay_fact_id)
            VALUES (:run_id, :source_fact_id, :replay_fact_id)
            ON CONFLICT (run_id, source_fact_id) DO UPDATE
            SET replay_fact_id = EXCLUDED.replay_fact_id
            """,
            {
                "run_id": run["id"],
                "source_fact_id": step["source_to_fact_id"],
                "replay_fact_id": replay_intent["to_fact_id"],
            },
        )
        sql.execute(
            conn,
            """
            UPDATE replay_steps
            SET status = 'concluded', concluded_at = :concluded_at
            WHERE run_id = :run_id AND step_index = :step_index
            """,
            {"concluded_at": now, "run_id": run["id"], "step_index": step["step_index"]},
        )


def _create_replay_intent(conn, run, step):
    source_intent = sql.fetchone(
        conn,
        """
        SELECT *
        FROM intents
        WHERE project_id = :project_id AND id = :intent_id
        """,
        {"project_id": run["source_project_id"], "intent_id": step["source_intent_id"]},
    )
    if source_intent is None:
        return f"Source intent {step['source_intent_id']} not found"

    mapped_sources: list[str] = []
    for source_fact_id in _intent_source_ids(conn, run["source_project_id"], source_intent["id"]):
        mapped = _mapped_fact_id(conn, run["id"], source_fact_id)
        if mapped is None:
            return f"Source fact {source_fact_id} is not mapped yet"
        mapped_sources.append(mapped)

    expected = sql.fetchone(
        conn,
        "SELECT description FROM facts WHERE project_id = :project_id AND id = :fact_id",
        {"project_id": run["source_project_id"], "fact_id": step["source_to_fact_id"]},
    )
    expected_description = expected["description"] if expected is not None else ""
    description = _replay_intent_description(source_intent, step["source_to_fact_id"], expected_description)
    now = utcnow()
    intent_id = next_intent_id(conn, run["replay_project_id"])
    sql.execute(
        conn,
        """
        INSERT INTO intents (
            id, project_id, to_fact_id, description, creator,
            worker, last_heartbeat_at, created_at, concluded_at
        ) VALUES (
            :id, :project_id, NULL, :description, :creator,
            NULL, NULL, :created_at, NULL
        )
        """,
        {
            "id": intent_id,
            "project_id": run["replay_project_id"],
            "description": description,
            "creator": _REPLAY_CREATOR,
            "created_at": now,
        },
    )
    for position, fact_id in enumerate(mapped_sources):
        sql.execute(
            conn,
            """
            INSERT INTO intent_sources (intent_id, project_id, fact_id, position)
            VALUES (:intent_id, :project_id, :fact_id, :position)
            """,
            {
                "intent_id": intent_id,
                "project_id": run["replay_project_id"],
                "fact_id": fact_id,
                "position": position,
            },
        )
    sql.execute(
        conn,
        """
        UPDATE replay_steps
        SET status = 'created', replay_intent_id = :replay_intent_id, created_at = :created_at
        WHERE run_id = :run_id AND step_index = :step_index
        """,
        {
            "replay_intent_id": intent_id,
            "created_at": now,
            "run_id": run["id"],
            "step_index": step["step_index"],
        },
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


def _mapped_fact_id(conn, run_id: str, source_fact_id: str) -> str | None:
    row = sql.fetchone(
        conn,
        """
        SELECT replay_fact_id
        FROM replay_fact_map
        WHERE run_id = :run_id AND source_fact_id = :source_fact_id
        """,
        {"run_id": run_id, "source_fact_id": source_fact_id},
    )
    return row["replay_fact_id"] if row is not None else None


def _replay_intent_description(source_intent, source_to_fact_id: str, expected_description: str) -> str:
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


def _complete_replay_project(conn, run):
    existing = sql.fetchall(
        conn,
        "SELECT * FROM intents WHERE project_id = :project_id AND to_fact_id = 'goal'",
        {"project_id": run["replay_project_id"]},
    )
    if len(existing) == 1:
        _mark_run_completed(conn, run["id"])
        return existing[0]
    if len(existing) > 1:
        raise HTTPException(409, "Replay project has multiple completion intents")

    source_completion = get_completion_intent_or_409(conn, run["source_project_id"])
    mapped_sources: list[str] = []
    for source_fact_id in _intent_source_ids(conn, run["source_project_id"], source_completion["id"]):
        mapped = _mapped_fact_id(conn, run["id"], source_fact_id)
        if mapped is None:
            raise HTTPException(409, f"Completion source fact {source_fact_id} is not mapped")
        mapped_sources.append(mapped)

    now = utcnow()
    intent_id = next_intent_id(conn, run["replay_project_id"])
    sql.execute(
        conn,
        """
        INSERT INTO intents (
            id, project_id, to_fact_id, description, creator, worker,
            last_heartbeat_at, created_at, concluded_at
        ) VALUES (
            :id, :project_id, 'goal', :description, :creator, :worker,
            :last_heartbeat_at, :created_at, :concluded_at
        )
        """,
        {
            "id": intent_id,
            "project_id": run["replay_project_id"],
            "description": run["completion_description"],
            "creator": _REPLAY_CREATOR,
            "worker": _REPLAY_CREATOR,
            "last_heartbeat_at": now,
            "created_at": now,
            "concluded_at": now,
        },
    )
    for position, fact_id in enumerate(mapped_sources):
        sql.execute(
            conn,
            """
            INSERT INTO intent_sources (intent_id, project_id, fact_id, position)
            VALUES (:intent_id, :project_id, :fact_id, :position)
            """,
            {
                "intent_id": intent_id,
                "project_id": run["replay_project_id"],
                "fact_id": fact_id,
                "position": position,
            },
        )
    sql.execute(
        conn,
        """
        UPDATE projects
        SET status = 'completed',
            reason_worker = NULL,
            reason_run_id = NULL,
            reason_trigger = NULL,
            reason_started_at = NULL,
            reason_last_heartbeat_at = NULL
        WHERE id = :project_id
        """,
        {"project_id": run["replay_project_id"]},
    )
    _mark_run_completed(conn, run["id"])
    return sql.fetchone(
        conn,
        "SELECT * FROM intents WHERE project_id = :project_id AND id = :intent_id",
        {"project_id": run["replay_project_id"], "intent_id": intent_id},
    )


def _mark_run_completed(conn, run_id: str) -> None:
    sql.execute(
        conn,
        """
        UPDATE replay_runs
        SET status = 'completed', completed_at = COALESCE(completed_at, :completed_at)
        WHERE id = :run_id
        """,
        {"completed_at": utcnow(), "run_id": run_id},
    )
