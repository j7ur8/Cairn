from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException

from cairn.server.db import get_conn
from cairn.server.models import (
    Fact,
    Hint,
    Intent,
    ProjectDetail,
    ReplayRunAdvanceResponse,
    ReplayRunCreateRequest,
    ReplayRunCreateResponse,
)
from cairn.server.routers.ai_profiles import persist_project_ai_selection
from cairn.server.services import (
    build_intents,
    check_project_completed,
    get_completion_intent_or_409,
    get_project_or_404,
    next_hint_id,
    next_intent_id,
    next_project_id,
    project_meta_from_row,
    utcnow,
)

router = APIRouter(tags=["replay"])

_REPO_ROOT = Path(__file__).resolve().parents[5]
_ATTACHMENTS_ROOT = Path(os.environ.get("CAIRN_ATTACHMENTS_ROOT", str(_REPO_ROOT / "datas" / "attachments")))
_REPLAY_CREATOR = "dispatcher.replay"


@router.post(
    "/projects/{project_id}/replay-runs",
    response_model=ReplayRunCreateResponse,
    status_code=201,
)
def create_replay_run(project_id: str, body: ReplayRunCreateRequest):
    replay_project_id: str | None = None
    run_id: str | None = None
    with get_conn() as conn:
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

        conn.execute(
            "INSERT INTO projects (id, title, status, created_at) VALUES (?, ?, 'stopped', ?)",
            (replay_project_id, body.title, now),
        )
        conn.execute(
            "INSERT INTO facts (id, project_id, description) VALUES (?, ?, ?)",
            ("origin", replay_project_id, body.origin),
        )
        conn.execute(
            "INSERT INTO facts (id, project_id, description) VALUES (?, ?, ?)",
            ("goal", replay_project_id, body.goal),
        )
        conn.execute(
            """
            INSERT INTO replay_runs (
                id, source_project_id, replay_project_id, status,
                completion_description, created_at
            ) VALUES (?, ?, ?, 'active', ?, ?)
            """,
            (run_id, project_id, replay_project_id, completion["description"], now),
        )
        conn.execute(
            "INSERT INTO replay_fact_map (run_id, source_fact_id, replay_fact_id) VALUES (?, 'origin', 'origin')",
            (run_id,),
        )
        conn.execute(
            "INSERT INTO replay_fact_map (run_id, source_fact_id, replay_fact_id) VALUES (?, 'goal', 'goal')",
            (run_id,),
        )
        for index, source_intent in enumerate(route):
            conn.execute(
                """
                INSERT INTO replay_steps (
                    run_id, step_index, source_intent_id, source_to_fact_id, status
                ) VALUES (?, ?, ?, ?, 'pending')
                """,
                (run_id, index, source_intent["id"], source_intent["to_fact_id"]),
            )

        for hint in body.hints or []:
            hid = next_hint_id(conn, replay_project_id)
            content = _rewrite_attachment_refs(hint.content, project_id, replay_project_id)
            conn.execute(
                "INSERT INTO hints (id, project_id, content, creator, created_at) VALUES (?, ?, ?, ?, ?)",
                (hid, replay_project_id, content, hint.creator, now),
            )

        if body.capabilities is not None:
            for capability_id in body.capabilities.mcp_server_ids:
                conn.execute(
                    """
                    INSERT INTO project_capabilities (project_id, kind, capability_id, created_at)
                    VALUES (?, 'mcp_server', ?, ?)
                    """,
                    (replay_project_id, capability_id, now),
                )
            for capability_id in body.capabilities.skill_ids:
                conn.execute(
                    """
                    INSERT INTO project_capabilities (project_id, kind, capability_id, created_at)
                    VALUES (?, 'skill', ?, ?)
                    """,
                    (replay_project_id, capability_id, now),
                )

        if body.role_id:
            _insert_role_snapshot(conn, replay_project_id, body.role_id, now)

        if body.ai_profiles is not None:
            persist_project_ai_selection(conn, replay_project_id, body.ai_profiles, now)

    try:
        _copy_project_attachments(project_id, replay_project_id)
        with get_conn() as conn:
            conn.execute("UPDATE projects SET status = 'active' WHERE id = ?", (replay_project_id,))
            detail = _project_detail(conn, replay_project_id)
            return ReplayRunCreateResponse(
                run_id=run_id,
                source_project_id=project_id,
                project=detail,
            )
    except Exception:
        if replay_project_id:
            shutil.rmtree(_ATTACHMENTS_ROOT / replay_project_id, ignore_errors=True)
            with get_conn() as conn:
                conn.execute("DELETE FROM projects WHERE id = ?", (replay_project_id,))
        raise


@router.post(
    "/projects/{project_id}/replay-runs/advance",
    response_model=ReplayRunAdvanceResponse,
)
def advance_replay_run(project_id: str):
    with get_conn() as conn:
        run = conn.execute(
            """
            SELECT *
            FROM replay_runs
            WHERE replay_project_id = ?
            """,
            (project_id,),
        ).fetchone()
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
    facts = conn.execute("SELECT * FROM facts WHERE project_id = ?", (project_id,)).fetchall()
    hints = conn.execute(
        "SELECT * FROM hints WHERE project_id = ? ORDER BY created_at",
        (project_id,),
    ).fetchall()
    return ProjectDetail(
        project=project_meta_from_row(row),
        facts=[Fact(**dict(fact)) for fact in facts],
        intents=build_intents(conn, project_id),
        hints=[Hint(**dict(hint)) for hint in hints],
    )


def _intent_source_ids(conn, project_id: str, intent_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT fact_id FROM intent_sources WHERE intent_id = ? AND project_id = ? ORDER BY rowid",
        (intent_id, project_id),
    ).fetchall()
    return [row["fact_id"] for row in rows]


def _extract_replay_route(conn, project_id: str, completion_source_ids: list[str]):
    route = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit_fact(fact_id: str) -> None:
        if fact_id in ("origin", "goal"):
            return
        rows = conn.execute(
            """
            SELECT *
            FROM intents
            WHERE project_id = ? AND to_fact_id = ?
            """,
            (project_id, fact_id),
        ).fetchall()
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


def _insert_role_snapshot(conn, project_id: str, role_id: str, now: str) -> None:
    role = conn.execute(
        """
        SELECT id, name, prompt, prompt_sha256
        FROM role_catalog
        WHERE id = ? AND available = 1
        """,
        (role_id,),
    ).fetchone()
    if role is None:
        raise HTTPException(404, f"Role {role_id} not found or unavailable")
    conn.execute(
        """
        INSERT INTO project_roles (
            project_id, role_id, role_name, role_prompt, role_prompt_sha256, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (project_id, role["id"], role["name"], role["prompt"], role["prompt_sha256"], now),
    )


def _copy_project_attachments(source_project_id: str, replay_project_id: str) -> Path | None:
    source = _ATTACHMENTS_ROOT / source_project_id
    if not source.exists() or not source.is_dir():
        return None
    target = _ATTACHMENTS_ROOT / replay_project_id
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
    return conn.execute(
        """
        SELECT *
        FROM replay_steps
        WHERE run_id = ?
        ORDER BY step_index
        """,
        (run_id,),
    ).fetchall()


def _sync_concluded_steps(conn, run) -> None:
    now = utcnow()
    steps = conn.execute(
        """
        SELECT *
        FROM replay_steps
        WHERE run_id = ? AND status = 'created' AND replay_intent_id IS NOT NULL
        ORDER BY step_index
        """,
        (run["id"],),
    ).fetchall()
    for step in steps:
        replay_intent = conn.execute(
            "SELECT * FROM intents WHERE project_id = ? AND id = ?",
            (run["replay_project_id"], step["replay_intent_id"]),
        ).fetchone()
        if replay_intent is None or replay_intent["to_fact_id"] is None or replay_intent["concluded_at"] is None:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO replay_fact_map (run_id, source_fact_id, replay_fact_id)
            VALUES (?, ?, ?)
            """,
            (run["id"], step["source_to_fact_id"], replay_intent["to_fact_id"]),
        )
        conn.execute(
            """
            UPDATE replay_steps
            SET status = 'concluded', concluded_at = ?
            WHERE run_id = ? AND step_index = ?
            """,
            (now, run["id"], step["step_index"]),
        )


def _create_replay_intent(conn, run, step):
    source_intent = conn.execute(
        """
        SELECT *
        FROM intents
        WHERE project_id = ? AND id = ?
        """,
        (run["source_project_id"], step["source_intent_id"]),
    ).fetchone()
    if source_intent is None:
        return f"Source intent {step['source_intent_id']} not found"

    mapped_sources: list[str] = []
    for source_fact_id in _intent_source_ids(conn, run["source_project_id"], source_intent["id"]):
        mapped = _mapped_fact_id(conn, run["id"], source_fact_id)
        if mapped is None:
            return f"Source fact {source_fact_id} is not mapped yet"
        mapped_sources.append(mapped)

    expected = conn.execute(
        "SELECT description FROM facts WHERE project_id = ? AND id = ?",
        (run["source_project_id"], step["source_to_fact_id"]),
    ).fetchone()
    expected_description = expected["description"] if expected is not None else ""
    description = _replay_intent_description(source_intent, step["source_to_fact_id"], expected_description)
    now = utcnow()
    intent_id = next_intent_id(conn, run["replay_project_id"])
    conn.execute(
        """
        INSERT INTO intents (
            id, project_id, to_fact_id, description, creator,
            worker, last_heartbeat_at, created_at, concluded_at
        ) VALUES (?, ?, NULL, ?, ?, NULL, NULL, ?, NULL)
        """,
        (intent_id, run["replay_project_id"], description, _REPLAY_CREATOR, now),
    )
    for fact_id in mapped_sources:
        conn.execute(
            "INSERT INTO intent_sources (intent_id, project_id, fact_id) VALUES (?, ?, ?)",
            (intent_id, run["replay_project_id"], fact_id),
        )
    conn.execute(
        """
        UPDATE replay_steps
        SET status = 'created', replay_intent_id = ?, created_at = ?
        WHERE run_id = ? AND step_index = ?
        """,
        (intent_id, now, run["id"], step["step_index"]),
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
    row = conn.execute(
        """
        SELECT replay_fact_id
        FROM replay_fact_map
        WHERE run_id = ? AND source_fact_id = ?
        """,
        (run_id, source_fact_id),
    ).fetchone()
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
    existing = conn.execute(
        "SELECT * FROM intents WHERE project_id = ? AND to_fact_id = 'goal'",
        (run["replay_project_id"],),
    ).fetchall()
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
    conn.execute(
        """
        INSERT INTO intents (
            id, project_id, to_fact_id, description, creator, worker,
            last_heartbeat_at, created_at, concluded_at
        ) VALUES (?, ?, 'goal', ?, ?, ?, ?, ?, ?)
        """,
        (
            intent_id,
            run["replay_project_id"],
            run["completion_description"],
            _REPLAY_CREATOR,
            _REPLAY_CREATOR,
            now,
            now,
            now,
        ),
    )
    for fact_id in mapped_sources:
        conn.execute(
            "INSERT INTO intent_sources (intent_id, project_id, fact_id) VALUES (?, ?, ?)",
            (intent_id, run["replay_project_id"], fact_id),
        )
    conn.execute(
        """
        UPDATE projects
        SET status = 'completed',
            reason_worker = NULL,
            reason_trigger = NULL,
            reason_started_at = NULL,
            reason_last_heartbeat_at = NULL
        WHERE id = ?
        """,
        (run["replay_project_id"],),
    )
    _mark_run_completed(conn, run["id"])
    return conn.execute(
        "SELECT * FROM intents WHERE project_id = ? AND id = ?",
        (run["replay_project_id"], intent_id),
    ).fetchone()


def _mark_run_completed(conn, run_id: str) -> None:
    conn.execute(
        """
        UPDATE replay_runs
        SET status = 'completed', completed_at = COALESCE(completed_at, ?)
        WHERE id = ?
        """,
        (utcnow(), run_id),
    )
