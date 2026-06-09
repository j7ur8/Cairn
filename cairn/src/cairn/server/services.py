from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from fastapi import HTTPException

from cairn.server.models import Intent, ProjectMeta, ProjectReason, ReasonState
from cairn.server.models_pkg.projects import parse_llm_hidden_event_kinds


REASON_FAILURE_BACKOFF_BASE_SECONDS = 30
REASON_FAILURE_BACKOFF_MAX_SECONDS = 300
REASON_FAILURE_BLOCK_THRESHOLD = 3
REASON_SUCCESS_OUTCOMES = {"success", "complete", "intents", "noop", "blocked"}
REASON_FAILURE_OUTCOMES = {"failed", "timeout", "rejected", "unhealthy", "cancelled"}

def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reason_trigger_hash(trigger: str) -> str:
    return sha256(trigger.encode("utf-8")).hexdigest()


def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _reason_backoff_until(now: str, failure_count: int) -> str:
    delay = min(
        REASON_FAILURE_BACKOFF_MAX_SECONDS,
        REASON_FAILURE_BACKOFF_BASE_SECONDS * (2 ** max(0, failure_count - 1)),
    )
    return (_parse_utc(now) + timedelta(seconds=delay)).strftime("%Y-%m-%dT%H:%M:%SZ")


def next_project_id(conn: Any) -> str:
    conn.execute("UPDATE counters SET value = value + 1 WHERE name = 'project'")
    row = conn.execute("SELECT value FROM counters WHERE name = 'project'").fetchone()
    return f"proj_{row['value']:03d}"


def _next_scoped_id(
    conn: Any, kind: str, prefix: str, project_id: str
) -> str:
    conn.execute(
        """
        INSERT INTO scoped_counters (project_id, kind, value)
        VALUES (?, ?, 0)
        ON CONFLICT (project_id, kind) DO NOTHING
        """,
        (project_id, kind),
    )
    conn.execute(
        "UPDATE scoped_counters SET value = value + 1 WHERE project_id = ? AND kind = ?",
        (project_id, kind),
    )
    row = conn.execute(
        "SELECT value FROM scoped_counters WHERE project_id = ? AND kind = ?",
        (project_id, kind),
    ).fetchone()
    assert row is not None
    return f"{prefix}{row['value']:03d}"


def next_fact_id(conn: Any, project_id: str) -> str:
    return _next_scoped_id(conn, "fact", "f", project_id)


def next_intent_id(conn: Any, project_id: str) -> str:
    return _next_scoped_id(conn, "intent", "i", project_id)


def next_hint_id(conn: Any, project_id: str) -> str:
    return _next_scoped_id(conn, "hint", "h", project_id)


def get_project_or_404(conn: Any, project_id: str) -> Any:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Project not found")
    return row


def check_project_active(conn: Any, project_id: str) -> Any:
    row = get_project_or_404(conn, project_id)
    if row["status"] != "active":
        raise HTTPException(403, f"Project is {row['status']}")
    return row


def check_project_hint_writable(conn: Any, project_id: str) -> Any:
    row = get_project_or_404(conn, project_id)
    if row["status"] not in ("active", "stopped", "completed"):
        raise HTTPException(403, f"Project is {row['status']}")
    return row


def check_project_completed(conn: Any, project_id: str) -> Any:
    row = get_project_or_404(conn, project_id)
    if row["status"] != "completed":
        raise HTTPException(403, f"Project is {row['status']}")
    return row


def validate_facts_exist(
    conn: Any, project_id: str, fact_ids: list[str]
) -> None:
    for fid in fact_ids:
        row = conn.execute(
            "SELECT 1 FROM facts WHERE id = ? AND project_id = ?", (fid, project_id)
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"Fact {fid} not found")


def validate_goal_not_in_sources(fact_ids: list[str]) -> None:
    if "goal" in fact_ids:
        raise HTTPException(400, "goal cannot be used in from")


def validate_intent_creator_worker(creator: str, worker: str | None) -> None:
    if worker is not None and worker != creator:
        raise HTTPException(400, "worker must be null or equal to creator")


def get_intent_or_404(
    conn: Any, project_id: str, intent_id: str
) -> Any:
    row = conn.execute(
        "SELECT * FROM intents WHERE id = ? AND project_id = ?",
        (intent_id, project_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Intent not found")
    return row


def get_claimable_open_intent_or_404(
    conn: Any, project_id: str, intent_id: str, worker: str
) -> Any:
    expire_workers(conn, project_id)
    row = get_intent_or_404(conn, project_id, intent_id)
    if row["to_fact_id"] is not None:
        raise HTTPException(409, "Intent already concluded")
    if row["worker"] is not None and row["worker"] != worker:
        raise HTTPException(409, f"Intent is currently claimed by {row['worker']}")
    return row


def claim_open_intent_or_409(
    conn: Any, project_id: str, intent_id: str, worker: str, now: str
) -> Any:
    get_claimable_open_intent_or_404(conn, project_id, intent_id, worker)
    cursor = conn.execute(
        """
        UPDATE intents
        SET worker = ?, last_heartbeat_at = ?
        WHERE id = ?
          AND project_id = ?
          AND to_fact_id IS NULL
          AND (worker IS NULL OR worker = ?)
        """,
        (worker, now, intent_id, project_id, worker),
    )
    if cursor.rowcount != 1:
        row = get_intent_or_404(conn, project_id, intent_id)
        if row["to_fact_id"] is not None:
            raise HTTPException(409, "Intent already concluded")
        if row["worker"] is not None and row["worker"] != worker:
            raise HTTPException(409, f"Intent is currently claimed by {row['worker']}")
        raise HTTPException(409, "Intent claim failed")
    updated = get_intent_or_404(conn, project_id, intent_id)
    if updated["to_fact_id"] is not None or updated["worker"] != worker:
        raise HTTPException(409, "Intent claim failed")
    return updated


def release_open_intent_or_409(
    conn: Any, project_id: str, intent_id: str, worker: str
) -> Any:
    row = get_releasable_open_intent_or_404(conn, project_id, intent_id, worker)
    if row["worker"] is None:
        return row
    cursor = conn.execute(
        """
        UPDATE intents
        SET worker = NULL
        WHERE id = ?
          AND project_id = ?
          AND to_fact_id IS NULL
          AND worker = ?
        """,
        (intent_id, project_id, worker),
    )
    if cursor.rowcount != 1:
        row = get_intent_or_404(conn, project_id, intent_id)
        if row["to_fact_id"] is not None:
            raise HTTPException(409, "Intent already concluded")
        if row["worker"] is not None and row["worker"] != worker:
            raise HTTPException(409, f"Intent is currently claimed by {row['worker']}")
        raise HTTPException(409, "Intent release failed")
    return get_intent_or_404(conn, project_id, intent_id)


def conclude_open_intent_or_409(
    conn: Any,
    project_id: str,
    intent_id: str,
    worker: str,
    fact_id: str,
    now: str,
) -> Any:
    get_claimable_open_intent_or_404(conn, project_id, intent_id, worker)
    cursor = conn.execute(
        """
        UPDATE intents
        SET to_fact_id = ?, worker = ?, last_heartbeat_at = ?, concluded_at = ?
        WHERE id = ?
          AND project_id = ?
          AND to_fact_id IS NULL
          AND (worker IS NULL OR worker = ?)
        """,
        (fact_id, worker, now, now, intent_id, project_id, worker),
    )
    if cursor.rowcount != 1:
        row = get_intent_or_404(conn, project_id, intent_id)
        if row["to_fact_id"] is not None:
            raise HTTPException(409, "Intent already concluded")
        if row["worker"] is not None and row["worker"] != worker:
            raise HTTPException(409, f"Intent is currently claimed by {row['worker']}")
        raise HTTPException(409, "Intent conclude failed")
    updated = get_intent_or_404(conn, project_id, intent_id)
    if updated["to_fact_id"] != fact_id or updated["worker"] != worker:
        raise HTTPException(409, "Intent conclude failed")
    return updated


def get_releasable_open_intent_or_404(
    conn: Any, project_id: str, intent_id: str, worker: str
) -> Any:
    expire_workers(conn, project_id)
    row = get_intent_or_404(conn, project_id, intent_id)
    if row["to_fact_id"] is not None:
        raise HTTPException(409, "Intent already concluded")
    if row["worker"] is None:
        return row
    if row["worker"] != worker:
        raise HTTPException(409, f"Intent is currently claimed by {row['worker']}")
    return row


def get_completion_intent_or_409(conn: Any, project_id: str) -> Any:
    rows = conn.execute(
        "SELECT * FROM intents WHERE project_id = ? AND to_fact_id = 'goal'",
        (project_id,),
    ).fetchall()
    if not rows:
        raise HTTPException(409, "Completed project is missing its completion intent")
    if len(rows) != 1:
        raise HTTPException(409, "Completed project has multiple completion intents")
    return rows[0]


def intent_to_model(conn: Any, row: Any, project_id: str) -> Intent:
    sources = conn.execute(
        "SELECT fact_id FROM intent_sources WHERE intent_id = ? AND project_id = ? ORDER BY rowid",
        (row["id"], project_id),
    ).fetchall()
    return Intent(
        id=row["id"],
        **{"from": [s["fact_id"] for s in sources]},
        to=row["to_fact_id"],
        description=row["description"],
        creator=row["creator"],
        worker=row["worker"],
        last_heartbeat_at=row["last_heartbeat_at"],
        created_at=row["created_at"],
        concluded_at=row["concluded_at"],
    )


def build_intents(conn: Any, project_id: str) -> list[Intent]:
    rows = conn.execute(
        "SELECT * FROM intents WHERE project_id = ? ORDER BY created_at",
        (project_id,),
    ).fetchall()
    return [intent_to_model(conn, r, project_id) for r in rows]


def get_intent_timeout(conn: Any) -> int:
    row = conn.execute("SELECT intent_timeout FROM settings WHERE rowid = 1").fetchone()
    return row["intent_timeout"]


def get_reason_timeout(conn: Any) -> int:
    row = conn.execute("SELECT reason_timeout FROM settings WHERE rowid = 1").fetchone()
    return row["reason_timeout"]


def project_reason_from_row(row: Any) -> ProjectReason | None:
    if row["reason_worker"] is None:
        return None
    return ProjectReason(
        worker=row["reason_worker"],
        run_id=row["reason_run_id"] if "reason_run_id" in row.keys() else None,
        trigger=row["reason_trigger"],
        started_at=row["reason_started_at"],
        last_heartbeat_at=row["reason_last_heartbeat_at"],
    )


def project_meta_from_row(row: Any) -> ProjectMeta:
    return ProjectMeta(
        id=row["id"],
        title=row["title"],
        status=row["status"],
        created_at=row["created_at"],
        reason=project_reason_from_row(row),
        llm_hidden_event_kinds=parse_llm_hidden_event_kinds(
            row["llm_hidden_event_kinds"] if "llm_hidden_event_kinds" in row.keys() else None
        ),
    )


def reason_state_from_row(row: Any) -> ReasonState:
    return ReasonState(
        project_id=row["project_id"],
        trigger=row["trigger"],
        trigger_hash=row["trigger_hash"],
        fact_count=row["fact_count"],
        hint_count=row["hint_count"],
        open_intent_count=row["open_intent_count"],
        outcome=row["outcome"],
        failure_count=row["failure_count"],
        last_error=row["last_error"],
        next_retry_at=row["next_retry_at"],
        updated_at=row["updated_at"],
    )


def get_project_reason_state(conn: Any, project_id: str) -> ReasonState | None:
    row = conn.execute(
        "SELECT * FROM project_reason_state WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    return reason_state_from_row(row)


def _same_reason_trigger_state(
    row: Any | None,
    trigger_hash: str,
    fact_count: int,
    hint_count: int,
    open_intent_count: int,
) -> bool:
    if row is None:
        return False
    return (
        row["trigger_hash"] == trigger_hash
        and row["fact_count"] == fact_count
        and row["hint_count"] == hint_count
        and row["open_intent_count"] == open_intent_count
    )


def reason_trigger_dispatch_blocker(
    conn: Any,
    project_id: str,
    trigger_hash: str,
    fact_count: int,
    hint_count: int,
    open_intent_count: int,
    now: str | None = None,
) -> str | None:
    row = conn.execute(
        "SELECT * FROM project_reason_state WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if not _same_reason_trigger_state(row, trigger_hash, fact_count, hint_count, open_intent_count):
        return None
    assert row is not None
    if row["outcome"] in REASON_SUCCESS_OUTCOMES:
        return f"reason trigger already consumed outcome={row['outcome']}"
    next_retry_at = row["next_retry_at"]
    if next_retry_at is not None and next_retry_at > (now or utcnow()):
        return f"reason trigger backoff until {next_retry_at}"
    return None


def clear_project_reason(conn: Any, project_id: str) -> None:
    conn.execute(
        """
        UPDATE projects
        SET reason_worker = NULL,
            reason_run_id = NULL,
            reason_trigger = NULL,
            reason_started_at = NULL,
            reason_last_heartbeat_at = NULL
        WHERE id = ?
        """,
        (project_id,),
    )


def claim_project_reason_or_409(
    conn: Any,
    project_id: str,
    worker: str,
    trigger: str,
    now: str,
    *,
    run_id: str | None = None,
    trigger_hash: str | None = None,
    fact_count: int = 0,
    hint_count: int = 0,
    open_intent_count: int = 0,
) -> Any:
    expire_reason_leases(conn, project_id)
    row = get_project_or_404(conn, project_id)
    if row["status"] != "active":
        raise HTTPException(403, f"Project is {row['status']}")
    trigger_hash = trigger_hash or reason_trigger_hash(trigger)
    blocker = reason_trigger_dispatch_blocker(
        conn,
        project_id,
        trigger_hash,
        fact_count,
        hint_count,
        open_intent_count,
        now,
    )
    if blocker is not None:
        raise HTTPException(409, blocker)
    current_worker = row["reason_worker"]
    if current_worker is not None and current_worker != worker:
        raise HTTPException(409, f"Project reason is currently claimed by {current_worker}")
    if current_worker == worker:
        return row

    cursor = conn.execute(
        """
        UPDATE projects
        SET reason_worker = ?,
            reason_run_id = ?,
            reason_trigger = ?,
            reason_started_at = ?,
            reason_last_heartbeat_at = ?
        WHERE id = ?
          AND status = 'active'
          AND reason_worker IS NULL
        """,
        (worker, run_id, trigger, now, now, project_id),
    )
    if cursor.rowcount != 1:
        row = get_project_or_404(conn, project_id)
        if row["status"] != "active":
            raise HTTPException(403, f"Project is {row['status']}")
        current_worker = row["reason_worker"]
        if current_worker is not None and current_worker != worker:
            raise HTTPException(409, f"Project reason is currently claimed by {current_worker}")
        raise HTTPException(409, "Project reason claim failed")
    return get_project_or_404(conn, project_id)


def finish_project_reason_or_409(
    conn: Any,
    project_id: str,
    worker: str,
    trigger: str,
    now: str,
    *,
    run_id: str | None = None,
    trigger_hash: str | None,
    fact_count: int,
    hint_count: int,
    open_intent_count: int,
    outcome: str,
    error: str | None,
) -> Any:
    row = get_project_or_404(conn, project_id)
    if row["status"] not in ("active", "completed", "stopped"):
        raise HTTPException(403, f"Project is {row['status']}")
    current_worker = row["reason_worker"]
    if row["status"] == "active" and current_worker is not None and current_worker != worker:
        raise HTTPException(409, f"Project reason is currently claimed by {current_worker}")
    current_run_id = row["reason_run_id"] if "reason_run_id" in row.keys() else None
    if row["status"] == "active" and run_id is not None and current_run_id is not None and current_run_id != run_id:
        raise HTTPException(409, "Project reason run has been superseded")

    trigger_hash = trigger_hash or reason_trigger_hash(trigger)
    previous = conn.execute(
        "SELECT * FROM project_reason_state WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    same_trigger = _same_reason_trigger_state(
        previous,
        trigger_hash,
        fact_count,
        hint_count,
        open_intent_count,
    )
    previous_failures = previous["failure_count"] if same_trigger and previous is not None else 0
    last_error = (error or "")[:4000]
    next_retry_at: str | None = None
    stored_outcome = outcome
    failure_count = 0
    if outcome in REASON_FAILURE_OUTCOMES:
        failure_count = previous_failures + 1
        if failure_count >= REASON_FAILURE_BLOCK_THRESHOLD:
            stored_outcome = "blocked"
            next_retry_at = None
        else:
            next_retry_at = _reason_backoff_until(now, failure_count)
    elif outcome not in REASON_SUCCESS_OUTCOMES:
        raise HTTPException(400, f"invalid reason outcome: {outcome}")

    conn.execute(
        """
        INSERT INTO project_reason_state (
            project_id, trigger, trigger_hash, fact_count, hint_count,
            open_intent_count, outcome, failure_count, last_error,
            next_retry_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(project_id) DO UPDATE SET
            trigger = excluded.trigger,
            trigger_hash = excluded.trigger_hash,
            fact_count = excluded.fact_count,
            hint_count = excluded.hint_count,
            open_intent_count = excluded.open_intent_count,
            outcome = excluded.outcome,
            failure_count = excluded.failure_count,
            last_error = excluded.last_error,
            next_retry_at = excluded.next_retry_at,
            updated_at = excluded.updated_at
        """,
        (
            project_id,
            trigger,
            trigger_hash,
            fact_count,
            hint_count,
            open_intent_count,
            stored_outcome,
            failure_count,
            last_error,
            next_retry_at,
            now,
        ),
    )
    if row["status"] == "active" and (current_worker is None or current_worker == worker):
        clear_project_reason(conn, project_id)
    return get_project_or_404(conn, project_id)


def heartbeat_project_reason_or_409(
    conn: Any, project_id: str, worker: str, now: str, run_id: str | None = None
) -> Any:
    expire_reason_leases(conn, project_id)
    row = get_project_or_404(conn, project_id)
    if row["status"] != "active":
        raise HTTPException(403, f"Project is {row['status']}")
    current_worker = row["reason_worker"]
    if current_worker is None:
        raise HTTPException(409, "Project reason is not currently claimed")
    if current_worker != worker:
        raise HTTPException(409, f"Project reason is currently claimed by {current_worker}")
    current_run_id = row["reason_run_id"] if "reason_run_id" in row.keys() else None
    if run_id is not None and current_run_id is not None and current_run_id != run_id:
        raise HTTPException(409, "Project reason run has been superseded")

    cursor = conn.execute(
        """
        UPDATE projects
        SET reason_last_heartbeat_at = ?
        WHERE id = ?
          AND status = 'active'
          AND reason_worker = ?
        """,
        (now, project_id, worker),
    )
    if cursor.rowcount != 1:
        row = get_project_or_404(conn, project_id)
        if row["status"] != "active":
            raise HTTPException(403, f"Project is {row['status']}")
        current_worker = row["reason_worker"]
        if current_worker is None:
            raise HTTPException(409, "Project reason is not currently claimed")
        if current_worker != worker:
            raise HTTPException(409, f"Project reason is currently claimed by {current_worker}")
        raise HTTPException(409, "Project reason heartbeat failed")
    return get_project_or_404(conn, project_id)


def release_project_reason_or_409(
    conn: Any, project_id: str, worker: str, run_id: str | None = None
) -> Any:
    expire_reason_leases(conn, project_id)
    row = get_project_or_404(conn, project_id)
    if row["status"] != "active":
        raise HTTPException(403, f"Project is {row['status']}")
    current_worker = row["reason_worker"]
    if current_worker is None:
        return row
    if current_worker != worker:
        raise HTTPException(409, f"Project reason is currently claimed by {current_worker}")
    current_run_id = row["reason_run_id"] if "reason_run_id" in row.keys() else None
    if run_id is not None and current_run_id is not None and current_run_id != run_id:
        raise HTTPException(409, "Project reason run has been superseded")

    cursor = conn.execute(
        """
        UPDATE projects
        SET reason_worker = NULL,
            reason_run_id = NULL,
            reason_trigger = NULL,
            reason_started_at = NULL,
            reason_last_heartbeat_at = NULL
        WHERE id = ?
          AND status = 'active'
          AND reason_worker = ?
        """,
        (project_id, worker),
    )
    if cursor.rowcount != 1:
        row = get_project_or_404(conn, project_id)
        if row["status"] != "active":
            raise HTTPException(403, f"Project is {row['status']}")
        current_worker = row["reason_worker"]
        if current_worker is None:
            return row
        if current_worker != worker:
            raise HTTPException(409, f"Project reason is currently claimed by {current_worker}")
        raise HTTPException(409, "Project reason release failed")
    return get_project_or_404(conn, project_id)


def expire_workers(conn: Any, project_id: str | None = None) -> None:
    timeout = get_intent_timeout(conn)
    now = utcnow()
    cutoff = (_parse_utc(now) - timedelta(seconds=timeout)).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = """
        UPDATE intents
        SET worker = NULL
        WHERE to_fact_id IS NULL
          AND worker IS NOT NULL
          AND last_heartbeat_at IS NOT NULL
          AND last_heartbeat_at < ?
    """
    params: tuple = (cutoff,)
    if project_id is not None:
        query = query.replace("WHERE ", "WHERE project_id = ? AND ", 1)
        params = (project_id, cutoff)
    conn.execute(query, params)


def expire_reason_leases(conn: Any, project_id: str | None = None) -> None:
    timeout = get_reason_timeout(conn)
    now = utcnow()
    cutoff = (_parse_utc(now) - timedelta(seconds=timeout)).strftime("%Y-%m-%dT%H:%M:%SZ")
    query = """
        UPDATE projects
        SET reason_worker = NULL,
            reason_run_id = NULL,
            reason_trigger = NULL,
            reason_started_at = NULL,
            reason_last_heartbeat_at = NULL
        WHERE reason_worker IS NOT NULL
          AND reason_last_heartbeat_at IS NOT NULL
          AND reason_last_heartbeat_at < ?
    """
    params: tuple = (cutoff,)
    if project_id is not None:
        query = query.replace("WHERE ", "WHERE id = ? AND ", 1)
        params = (project_id, cutoff)
    conn.execute(query, params)
