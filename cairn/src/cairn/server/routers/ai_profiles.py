"""System-wide AI profile catalog and project-level primary/fallback selection.

AI profiles describe a concrete AI worker configuration (model, base URL, and
an env-var name that holds the API key). The settings UI manages the
shared catalog; new projects and replay runs pick exactly one *primary* and
an ordered list of *fallback* profiles. The dispatcher reads the project
snapshot and constrains worker selection to those profiles, applying
primary → fallback ordering before the existing worker priority.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable

import sqlite3
from fastapi import APIRouter, HTTPException

from cairn.server.db import get_conn
from cairn.server.models import (
    AiProfile,
    AiProfileCreate,
    AiProfileHealthReportRequest,
    AiProfileSelection,
    AiProfileSyncRequest,
    AiProfileSyncWorker,
    AiProfileUpdate,
    AiProfileWithHealth,
    HealthCheckResult,
    ProjectAiProfileSnapshot,
    ProjectAiProfilesResponse,
    auth_env_warning,
)


router = APIRouter(tags=["ai-profiles"])


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_profile(row: sqlite3.Row) -> AiProfile:
    return AiProfile(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        worker_type=row["worker_type"],
        provider=row["provider"],
        base_url=row["base_url"],
        model=row["model"],
        api_key_env=row["api_key_env"],
        available=bool(row["available"]),
        detail=row["detail"],
        healthcheck_timeout=row["healthcheck_timeout"] or 1.0,
        warnings=_compute_warnings(row["worker_type"], row["api_key_env"]),
        seeded_from_worker=row["seeded_from_worker"],
        last_health_ok=bool(row["last_health_ok"]) if row["last_health_ok"] is not None else None,
        last_health_message=row["last_health_message"] or "",
        last_health_at=row["last_health_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _compute_warnings(worker_type: str, api_key_env: str) -> list[str]:
    warning = auth_env_warning(worker_type, api_key_env)
    return [warning] if warning else []


def _new_profile_id() -> str:
    return f"ai_{uuid.uuid4().hex[:12]}"


def _seed_id(worker_name: str) -> str:
    """Deterministic id for a worker-derived profile, idempotent on re-seed."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in worker_name)
    safe = safe.strip("_") or "worker"
    return f"ai_seed_{safe}"[:64]


@router.get("/ai-profiles", response_model=list[AiProfile])
def list_ai_profiles():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_profiles ORDER BY created_at DESC, id"
        ).fetchall()
    return [_row_to_profile(row) for row in rows]


@router.post("/ai-profiles", response_model=AiProfileWithHealth, status_code=201)
def create_ai_profile(body: AiProfileCreate):
    pid = _new_profile_id()
    now = _utcnow()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO ai_profiles (
                id, name, description, worker_type, provider, base_url,
                model, api_key_env, available, detail,
                healthcheck_timeout,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pid, body.name, body.description, body.worker_type,
                body.provider, body.base_url, body.model, body.api_key_env,
                1 if body.available else 0, body.detail,
                body.healthcheck_timeout,
                now, now,
            ),
        )
        row = conn.execute("SELECT * FROM ai_profiles WHERE id = ?", (pid,)).fetchone()
    profile = _row_to_profile(row)
    return AiProfileWithHealth(
        **profile.model_dump(),
        health=HealthCheckResult(ok=True, checks=[]),
    )


@router.get("/ai-profiles/{profile_id}", response_model=AiProfile)
def get_ai_profile(profile_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM ai_profiles WHERE id = ?", (profile_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"ai profile not found: {profile_id}")
    return _row_to_profile(row)


@router.put("/ai-profiles/{profile_id}", response_model=AiProfileWithHealth)
def update_ai_profile(profile_id: str, body: AiProfileUpdate):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM ai_profiles WHERE id = ?", (profile_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"ai profile not found: {profile_id}")
        updates: dict[str, object] = {}
        for field in (
            "name", "description", "worker_type", "provider", "base_url",
            "model", "api_key_env", "detail", "healthcheck_timeout",
        ):
            value = getattr(body, field)
            if value is not None:
                updates[field] = value
        if body.available is not None:
            updates["available"] = 1 if body.available else 0
        if updates:
            updates["updated_at"] = _utcnow()
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [profile_id]
            conn.execute(
                f"UPDATE ai_profiles SET {set_clause} WHERE id = ?",
                values,
            )
        row = conn.execute("SELECT * FROM ai_profiles WHERE id = ?", (profile_id,)).fetchone()
    profile = _row_to_profile(row)
    return AiProfileWithHealth(
        **profile.model_dump(),
        health=HealthCheckResult(ok=True, checks=[]),
    )


@router.delete("/ai-profiles/{profile_id}", status_code=204)
def delete_ai_profile(profile_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM ai_profiles WHERE id = ?", (profile_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"ai profile not found: {profile_id}")
        # Snapshots are intentionally preserved: project_ai_profiles stores a
        # full copy of the profile fields at selection time, so historical
        # projects still know what they were configured to use.
        conn.execute("DELETE FROM ai_profiles WHERE id = ?", (profile_id,))
    return None


# ---------------------------------------------------------------------------
# Sync + health report
# ---------------------------------------------------------------------------


@router.post("/ai-profiles/sync", response_model=list[AiProfileWithHealth])
def sync_ai_profiles(body: AiProfileSyncRequest):
    """Idempotently upsert AI profiles derived from ``dispatch.yaml`` workers.

    Rows are keyed by ``seeded_from_worker = body.workers[i].name``. Workers
    whose ``worker_type`` is not in the supported set (``codex`` /
    ``claudecode``) are dropped silently with a debug log. Workers that
    appear in dispatch.yaml but not in the request body are NOT deleted
    automatically — operators control that via explicit delete calls.
    """
    supported = {"codex", "claudecode"}
    now = _utcnow()
    accepted: list[str] = []
    dropped: list[tuple[str, str]] = []
    with get_conn() as conn:
        for worker in body.workers:
            if worker.worker_type not in supported:
                dropped.append((worker.name, f"unsupported worker_type: {worker.worker_type}"))
                continue
            profile_id = _seed_id(worker.name)
            existing = conn.execute(
                "SELECT id, created_at FROM ai_profiles WHERE id = ? OR seeded_from_worker = ?",
                (profile_id, worker.name),
            ).fetchone()
            warnings = _compute_warnings(worker.worker_type, worker.api_key_env)
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO ai_profiles (
                        id, name, description, worker_type, provider, base_url,
                        model, api_key_env, available, detail,
                        healthcheck_timeout, seeded_from_worker,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 1.0, ?, ?, ?)
                    """,
                    (
                        profile_id, worker.name, "",
                        worker.worker_type, worker.provider, worker.base_url,
                        worker.model, worker.api_key_env, "",
                        worker.name, now, now,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE ai_profiles SET
                        name = ?, worker_type = ?, provider = ?, base_url = ?,
                        model = ?, api_key_env = ?, available = 1,
                        seeded_from_worker = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        worker.name, worker.worker_type, worker.provider,
                        worker.base_url, worker.model, worker.api_key_env,
                        worker.name, now, existing["id"],
                    ),
                )
            accepted.append(worker.name)
        conn.commit()
    for name, reason in dropped:
        import logging
        logging.getLogger(__name__).info(
            "ai_profile sync dropped worker=%s reason=%s", name, reason,
        )
    return list_ai_profiles_with_health()


@router.post("/ai-profiles/health-report", status_code=204)
def post_health_report(body: AiProfileHealthReportRequest):
    """Dispatcher-side probe results, applied to the catalog.

    The dispatcher runs the real probe (env var resolution + TCP connect)
    because the server cannot see the operator's secrets. After this
    endpoint is called, ``available`` reflects the latest probe outcome.
    """
    if not body.reports:
        return None
    now = _utcnow()
    with get_conn() as conn:
        for report in body.reports:
            row = conn.execute(
                "SELECT id FROM ai_profiles WHERE id = ?", (report.profile_id,),
            ).fetchone()
            if row is None:
                continue
            conn.execute(
                """
                UPDATE ai_profiles SET
                    available = ?,
                    last_health_ok = ?,
                    last_health_message = ?,
                    last_health_at = ?
                WHERE id = ?
                """,
                (
                    1 if report.ok else 0,
                    1 if report.ok else 0,
                    report.message or "",
                    now,
                    report.profile_id,
                ),
            )
        conn.commit()
    return None


def list_ai_profiles_with_health() -> list[AiProfileWithHealth]:
    """Return all profiles wrapped in ``AiProfileWithHealth``.

    The server does not run the probe itself; the dispatcher is the
    authoritative source of truth for the probe (because it has the env
    vars and the network). This helper just rolls the last known
    ``last_health_*`` columns into a ``HealthCheckResult`` payload so the
    UI can render a single "health" badge per row.
    """
    from cairn.server.models import HealthCheckItem
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_profiles ORDER BY created_at DESC, id"
        ).fetchall()
    result: list[AiProfileWithHealth] = []
    for row in rows:
        profile = _row_to_profile(row)
        ok = bool(profile.last_health_ok) if profile.last_health_ok is not None else True
        checks: list[HealthCheckItem] = []
        if profile.last_health_at is not None:
            checks.append(HealthCheckItem(
                name="dispatcher_probe",
                ok=ok,
                message=profile.last_health_message or "ok",
            ))
        result.append(AiProfileWithHealth(
            **profile.model_dump(),
            health=HealthCheckResult(ok=ok, checks=checks),
        ))
    return result


# ---------------------------------------------------------------------------
# Project snapshot helpers (unchanged)
# ---------------------------------------------------------------------------


def _load_snapshots(conn: sqlite3.Connection, project_id: str) -> list[ProjectAiProfileSnapshot]:
    rows = conn.execute(
        """
        SELECT profile_id, role, position,
               snapshot_name, snapshot_worker_type, snapshot_provider,
               snapshot_base_url, snapshot_model, snapshot_api_key_env
        FROM project_ai_profiles
        WHERE project_id = ?
        ORDER BY role, position
        """,
        (project_id,),
    ).fetchall()
    return [
        ProjectAiProfileSnapshot(
            profile_id=row["profile_id"],
            role=row["role"],
            position=row["position"],
            snapshot_name=row["snapshot_name"],
            snapshot_worker_type=row["snapshot_worker_type"],
            snapshot_provider=row["snapshot_provider"],
            snapshot_base_url=row["snapshot_base_url"],
            snapshot_model=row["snapshot_model"],
            snapshot_api_key_env=row["snapshot_api_key_env"],
        )
        for row in rows
    ]


def _selection_from_snapshots(snapshots: Iterable[ProjectAiProfileSnapshot]) -> AiProfileSelection:
    primary: str | None = None
    fallback: list[str] = []
    for snap in snapshots:
        if snap.role == "primary" and primary is None:
            primary = snap.profile_id
        elif snap.role == "fallback":
            fallback.append(snap.profile_id)
    return AiProfileSelection(primary_profile_id=primary, fallback_profile_ids=fallback)


@router.get("/projects/{project_id}/ai-profiles", response_model=ProjectAiProfilesResponse)
def get_project_ai_profiles(project_id: str):
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
            raise HTTPException(404, f"project not found: {project_id}")
        catalog = [
            _row_to_profile(row)
            for row in conn.execute("SELECT * FROM ai_profiles ORDER BY id").fetchall()
        ]
        snapshots = _load_snapshots(conn, project_id)
        selection = _selection_from_snapshots(snapshots)
        available_ids = {item.id for item in catalog if item.available}
        unavailable = sorted({
            snap.profile_id for snap in snapshots
            if snap.profile_id not in available_ids
        })
        return ProjectAiProfilesResponse(
            catalog=catalog,
            selection=selection,
            snapshots=snapshots,
            unavailable_profile_ids=unavailable,
        )


def persist_project_ai_selection(
    conn: sqlite3.Connection,
    project_id: str,
    selection: AiProfileSelection,
    now: str,
) -> None:
    """Store the project AI selection as snapshots, replacing any prior one.

    The catalog table is consulted for the current profile values; if a
    referenced profile is missing, the request is rejected with 400 by the
    caller before we reach this function.
    """
    referenced: list[str] = []
    if selection.primary_profile_id:
        referenced.append(selection.primary_profile_id)
    referenced.extend(selection.fallback_profile_ids)
    rows = conn.execute(
        f"SELECT * FROM ai_profiles WHERE id IN ({','.join('?' * len(referenced))})",
        referenced,
    ).fetchall() if referenced else []
    by_id = {row["id"]: row for row in rows}
    missing = [pid for pid in referenced if pid not in by_id]
    if missing:
        raise HTTPException(400, f"ai profile ids not found: {', '.join(missing)}")
    unavailable = [pid for pid in referenced if not by_id[pid]["available"]]
    if unavailable:
        raise HTTPException(400, f"ai profile ids unavailable: {', '.join(unavailable)}")

    conn.execute("DELETE FROM project_ai_profiles WHERE project_id = ?", (project_id,))
    if selection.primary_profile_id:
        profile = by_id[selection.primary_profile_id]
        conn.execute(
            """
            INSERT INTO project_ai_profiles (
                project_id, profile_id, role, position,
                snapshot_name, snapshot_worker_type, snapshot_provider,
                snapshot_base_url, snapshot_model, snapshot_api_key_env,
                created_at
            ) VALUES (?, ?, 'primary', 0, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, selection.primary_profile_id,
                profile["name"], profile["worker_type"], profile["provider"],
                profile["base_url"], profile["model"], profile["api_key_env"], now,
            ),
        )
    for position, profile_id in enumerate(selection.fallback_profile_ids):
        if profile_id == selection.primary_profile_id:
            continue
        profile = by_id[profile_id]
        conn.execute(
            """
            INSERT INTO project_ai_profiles (
                project_id, profile_id, role, position,
                snapshot_name, snapshot_worker_type, snapshot_provider,
                snapshot_base_url, snapshot_model, snapshot_api_key_env,
                created_at
            ) VALUES (?, ?, 'fallback', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, profile_id, position,
                profile["name"], profile["worker_type"], profile["provider"],
                profile["base_url"], profile["model"], profile["api_key_env"], now,
            ),
        )
