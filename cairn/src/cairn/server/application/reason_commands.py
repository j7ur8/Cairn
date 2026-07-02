from __future__ import annotations

from typing import Any

from cairn.server.domain.projects import require_project
from cairn.server.domain.reason import (
    claim_failed,
    finish_state,
    heartbeat_failed,
    reason_trigger_hash,
    release_failed,
    should_clear_reason_after_finish,
    validate_reason_claimable,
    validate_reason_finishable,
    validate_reason_heartbeatable,
    validate_reason_releasable,
)
from cairn.server.domain.time import utcnow
from cairn.server.mappers.projects import project_meta_from_row, reason_state_from_row
from cairn.server.repositories.leases import LeaseRepository
from cairn.server.repositories.projects import ProjectRepository
from cairn.server.repositories.reason import ReasonRepository
from cairn.server.schemas import (
    HeartbeatRequest,
    ReasonClaimRequest,
    ReasonFinishRequest,
    ReasonState,
)
from cairn.shared.contracts import ProjectMeta


def claim_reason(conn: Any, project_id: str, body: ReasonClaimRequest) -> ProjectMeta:
    now = utcnow()
    LeaseRepository(conn).expire_reason_leases(project_id)
    projects = ProjectRepository(conn)
    reason = ReasonRepository(conn)
    row = require_project(projects.get(project_id))
    validate_reason_claimable(row, body.worker, body.run_id)
    if row["reason_worker"] is None:
        if reason.claim_project_reason(
            project_id,
            worker=body.worker,
            run_id=body.run_id,
            trigger=body.trigger,
            now=now,
        ) != 1:
            claim_failed(require_project(projects.get(project_id)), body.worker, body.run_id)
        projects.bump_revisions(project_id, graph=True)
    updated = require_project(projects.get(project_id))
    return project_meta_from_row(updated)


def heartbeat_reason(conn: Any, project_id: str, body: HeartbeatRequest) -> ProjectMeta:
    now = utcnow()
    LeaseRepository(conn).expire_reason_leases(project_id)
    projects = ProjectRepository(conn)
    row = require_project(projects.get(project_id))
    validate_reason_heartbeatable(row, body.worker, body.run_id)
    if ReasonRepository(conn).heartbeat_project_reason(project_id, worker=body.worker, now=now) != 1:
        heartbeat_failed(require_project(projects.get(project_id)), body.worker, body.run_id)
    projects.bump_revisions(project_id, graph=True)
    updated = require_project(projects.get(project_id))
    return project_meta_from_row(updated)


def release_reason(conn: Any, project_id: str, body: HeartbeatRequest) -> ProjectMeta:
    LeaseRepository(conn).expire_reason_leases(project_id)
    projects = ProjectRepository(conn)
    row = require_project(projects.get(project_id))
    validate_reason_releasable(row, body.worker, body.run_id)
    if row["reason_worker"] is not None:
        if ReasonRepository(conn).release_project_reason(project_id, worker=body.worker) != 1:
            release_failed(require_project(projects.get(project_id)), body.worker, body.run_id)
        projects.bump_revisions(project_id, graph=True)
    updated = require_project(projects.get(project_id))
    return project_meta_from_row(updated)


def reason_state(conn: Any, project_id: str) -> ReasonState | None:
    require_project(ProjectRepository(conn).get(project_id))
    row = ReasonRepository(conn).get_state(project_id)
    return reason_state_from_row(row) if row is not None else None


def finish_reason(conn: Any, project_id: str, body: ReasonFinishRequest) -> ProjectMeta:
    now = utcnow()
    projects = ProjectRepository(conn)
    reason = ReasonRepository(conn)
    row = require_project(projects.get(project_id))
    validate_reason_finishable(row, body.worker, body.run_id)
    state = finish_state(
        body.trigger,
        trigger_hash=body.trigger_hash or reason_trigger_hash(body.trigger),
        outcome=body.outcome,
        error=body.error,
    )
    reason.upsert_state(
        project_id,
        trigger=body.trigger,
        fact_count=body.fact_count,
        hint_count=body.hint_count,
        open_intent_count=body.open_intent_count,
        state=state,
        now=now,
    )
    if should_clear_reason_after_finish(row, body.worker):
        cleared = reason.clear_project_reason_if_owner(project_id, worker=body.worker, run_id=body.run_id)
        if cleared:
            projects.bump_revisions(project_id, graph=True)
    updated = require_project(projects.get(project_id))
    return project_meta_from_row(updated)
