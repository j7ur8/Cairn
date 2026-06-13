from __future__ import annotations

from typing import Any

from cairn.server.models_pkg import ReasonState
from cairn.shared.contracts import ProjectMeta, ProjectReason, parse_llm_hidden_event_kinds


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
