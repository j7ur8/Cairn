from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from fastapi import HTTPException

from cairn.server.models_pkg.intents import ReasonState
from cairn.server.models_pkg.projects import Intent, ProjectMeta, ProjectReason
from cairn.server.models_pkg.projects import parse_llm_hidden_event_kinds
from cairn.server.repositories import sql

REASON_SUCCESS_OUTCOMES = {"success", "complete", "intents", "noop"}
REASON_FAILURE_OUTCOMES = {"failed", "timeout", "rejected", "unhealthy", "cancelled"}

def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reason_trigger_hash(trigger: str) -> str:
    return sha256(trigger.encode("utf-8")).hexdigest()


def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def next_project_id(conn: Any) -> str:
    sql.execute(conn, "UPDATE counters SET value = value + 1 WHERE name = 'project'")
    row = sql.fetchone(conn, "SELECT value FROM counters WHERE name = 'project'")
    return f"proj_{row['value']:03d}"


def _next_scoped_id(
    conn: Any, kind: str, prefix: str, project_id: str
) -> str:
    sql.execute(
        conn,
        """
        INSERT INTO scoped_counters (project_id, kind, value)
        VALUES (:project_id, :kind, 0)
        ON CONFLICT (project_id, kind) DO NOTHING
        """,
        {"project_id": project_id, "kind": kind},
    )
    sql.execute(
        conn,
        "UPDATE scoped_counters SET value = value + 1 WHERE project_id = :project_id AND kind = :kind",
        {"project_id": project_id, "kind": kind},
    )
    row = sql.fetchone(
        conn,
        "SELECT value FROM scoped_counters WHERE project_id = :project_id AND kind = :kind",
        {"project_id": project_id, "kind": kind},
    )
    assert row is not None
    return f"{prefix}{row['value']:03d}"


def next_fact_id(conn: Any, project_id: str) -> str:
    return _next_scoped_id(conn, "fact", "f", project_id)


def next_intent_id(conn: Any, project_id: str) -> str:
    return _next_scoped_id(conn, "intent", "i", project_id)


def next_hint_id(conn: Any, project_id: str) -> str:
    return _next_scoped_id(conn, "hint", "h", project_id)


def get_project_or_404(conn: Any, project_id: str) -> Any:
    row = sql.fetchone(conn, "SELECT * FROM projects WHERE id = :project_id", {"project_id": project_id})
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
        row = sql.fetchone(
            conn,
            "SELECT 1 FROM facts WHERE id = :fact_id AND project_id = :project_id",
            {"fact_id": fid, "project_id": project_id},
        )
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
    row = sql.fetchone(
        conn,
        "SELECT * FROM intents WHERE id = :intent_id AND project_id = :project_id",
        {"intent_id": intent_id, "project_id": project_id},
    )
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
    cursor = sql.execute(
        conn,
        """
        UPDATE intents
        SET worker = :worker, last_heartbeat_at = :now
        WHERE id = :intent_id
          AND project_id = :project_id
          AND to_fact_id IS NULL
          AND (worker IS NULL OR worker = :worker)
        """,
        {"worker": worker, "now": now, "intent_id": intent_id, "project_id": project_id},
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
    cursor = sql.execute(
        conn,
        """
        UPDATE intents
        SET worker = NULL
        WHERE id = :intent_id
          AND project_id = :project_id
          AND to_fact_id IS NULL
          AND worker = :worker
        """,
        {"intent_id": intent_id, "project_id": project_id, "worker": worker},
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
    cursor = sql.execute(
        conn,
        """
        UPDATE intents
        SET to_fact_id = :fact_id, worker = :worker, last_heartbeat_at = :now, concluded_at = :now
        WHERE id = :intent_id
          AND project_id = :project_id
          AND to_fact_id IS NULL
          AND (worker IS NULL OR worker = :worker)
        """,
        {"fact_id": fact_id, "worker": worker, "now": now, "intent_id": intent_id, "project_id": project_id},
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
    rows = sql.fetchall(
        conn,
        "SELECT * FROM intents WHERE project_id = :project_id AND to_fact_id = 'goal'",
        {"project_id": project_id},
    )
    if not rows:
        raise HTTPException(409, "Completed project is missing its completion intent")
    if len(rows) != 1:
        raise HTTPException(409, "Completed project has multiple completion intents")
    return rows[0]


def intent_to_model(conn: Any, row: Any, project_id: str) -> Intent:
    sources = sql.fetchall(
        conn,
        """
        SELECT fact_id
        FROM intent_sources
        WHERE intent_id = :intent_id AND project_id = :project_id
        ORDER BY position, fact_id
        """,
        {"intent_id": row["id"], "project_id": project_id},
    )
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
    rows = sql.fetchall(
        conn,
        "SELECT * FROM intents WHERE project_id = :project_id ORDER BY created_at",
        {"project_id": project_id},
    )
    return [intent_to_model(conn, r, project_id) for r in rows]


def get_intent_timeout(conn: Any) -> int:
    row = sql.fetchone(conn, "SELECT intent_timeout FROM settings WHERE id = 1")
    return row["intent_timeout"]


def get_reason_timeout(conn: Any) -> int:
    row = sql.fetchone(conn, "SELECT reason_timeout FROM settings WHERE id = 1")
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
    row = sql.fetchone(
        conn,
        "SELECT * FROM project_reason_state WHERE project_id = :project_id",
        {"project_id": project_id},
    )
    if row is None:
        return None
    return reason_state_from_row(row)


def clear_project_reason(conn: Any, project_id: str) -> None:
    sql.execute(
        conn,
        """
        UPDATE projects
        SET reason_worker = NULL,
            reason_run_id = NULL,
            reason_trigger = NULL,
            reason_started_at = NULL,
            reason_last_heartbeat_at = NULL
        WHERE id = :project_id
        """,
        {"project_id": project_id},
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
    current_worker = row["reason_worker"]
    if current_worker is not None and current_worker != worker:
        raise HTTPException(409, f"Project reason is currently claimed by {current_worker}")
    if current_worker == worker:
        return row

    cursor = sql.execute(
        conn,
        """
        UPDATE projects
        SET reason_worker = :worker,
            reason_run_id = :run_id,
            reason_trigger = :trigger,
            reason_started_at = :now,
            reason_last_heartbeat_at = :now
        WHERE id = :project_id
          AND status = 'active'
          AND reason_worker IS NULL
        """,
        {"worker": worker, "run_id": run_id, "trigger": trigger, "now": now, "project_id": project_id},
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
    last_error = (error or "")[:4000]
    next_retry_at: str | None = None
    stored_outcome = outcome
    failure_count = 0
    if outcome in REASON_FAILURE_OUTCOMES:
        failure_count = 1
        next_retry_at = None
    elif outcome not in REASON_SUCCESS_OUTCOMES:
        raise HTTPException(400, f"invalid reason outcome: {outcome}")

    sql.execute(
        conn,
        """
        INSERT INTO project_reason_state (
            project_id, trigger, trigger_hash, fact_count, hint_count,
            open_intent_count, outcome, failure_count, last_error,
            next_retry_at, updated_at
        ) VALUES (
            :project_id, :trigger, :trigger_hash, :fact_count, :hint_count,
            :open_intent_count, :outcome, :failure_count, :last_error,
            :next_retry_at, :updated_at
        )
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
        {
            "project_id": project_id,
            "trigger": trigger,
            "trigger_hash": trigger_hash,
            "fact_count": fact_count,
            "hint_count": hint_count,
            "open_intent_count": open_intent_count,
            "outcome": stored_outcome,
            "failure_count": failure_count,
            "last_error": last_error,
            "next_retry_at": next_retry_at,
            "updated_at": now,
        },
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

    cursor = sql.execute(
        conn,
        """
        UPDATE projects
        SET reason_last_heartbeat_at = :now
        WHERE id = :project_id
          AND status = 'active'
          AND reason_worker = :worker
        """,
        {"now": now, "project_id": project_id, "worker": worker},
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

    cursor = sql.execute(
        conn,
        """
        UPDATE projects
        SET reason_worker = NULL,
            reason_run_id = NULL,
            reason_trigger = NULL,
            reason_started_at = NULL,
            reason_last_heartbeat_at = NULL
        WHERE id = :project_id
          AND status = 'active'
          AND reason_worker = :worker
        """,
        {"project_id": project_id, "worker": worker},
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
          AND last_heartbeat_at < :cutoff
    """
    params: dict[str, str] = {"cutoff": cutoff}
    if project_id is not None:
        query = query.replace("WHERE ", "WHERE project_id = :project_id AND ", 1)
        params["project_id"] = project_id
    sql.execute(conn, query, params)


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
          AND reason_last_heartbeat_at < :cutoff
    """
    params: dict[str, str] = {"cutoff": cutoff}
    if project_id is not None:
        query = query.replace("WHERE ", "WHERE id = :project_id AND ", 1)
        params["project_id"] = project_id
    sql.execute(conn, query, params)
