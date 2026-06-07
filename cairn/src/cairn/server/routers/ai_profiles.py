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

from cairn.server.db import get_conn, with_immediate_tx
from cairn.server.security.secrets import decrypt_secret, encrypt_secret
from cairn.server.models import (
    AiProfile,
    AiProfileCreate,
    AiProfileHealthReportRequest,
    AiProfileModelsReportRequest,
    AiProfileSelection,
    AiProfileSyncRequest,
    AiProfileSyncWorker,
    AiProfileUpdate,
    AiProfileWithHealth,
    HealthCheckResult,
    ProjectAiProfileSnapshot,
    ProjectAiProfilesResponse,
    TaskAiProfileSelections,
    auth_env_warning,
)


router = APIRouter(tags=["ai-profiles"])


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_models(value: str | None, *, fallback: str) -> list[str]:
    models = [item for item in (value or "").split("\n") if item]
    if fallback and fallback not in models:
        models.insert(0, fallback)
    return models


def _profile_select_sql(where: str = "", order_by: str = "p.created_at DESC, p.id") -> str:
    where_clause = f"WHERE {where}" if where else ""
    return f"""
        SELECT p.*,
               (
                   SELECT group_concat(model, char(10))
                   FROM (
                       SELECT model
                       FROM ai_profile_models
                       WHERE profile_id = p.id
                       ORDER BY model
                   )
               ) AS models
        FROM ai_profiles p
        {where_clause}
        ORDER BY {order_by}
    """


def _row_to_profile(row: sqlite3.Row) -> AiProfile:
    model_list = _parse_models(row["models"] if "models" in row.keys() else None, fallback=row["model"])
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
        model_reasoning_effort=row["model_reasoning_effort"] if "model_reasoning_effort" in row.keys() else None,
        warnings=_compute_warnings(row["worker_type"], row["api_key_env"]),
        seeded_from_worker=row["seeded_from_worker"],
        last_health_ok=bool(row["last_health_ok"]) if row["last_health_ok"] is not None else None,
        last_health_message=row["last_health_message"] or "",
        last_health_at=row["last_health_at"],
        models=model_list,
        # Prefer the encrypted column; fall back to the legacy
        # plaintext column for rows written before the migration. The
        # sk field on the model is masked (sk_set / sk_preview) on the
        # read path so the plaintext is never returned to the SPA.
        sk=_resolve_sk_from_row(row),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _resolve_sk_from_row(row: sqlite3.Row) -> str:
    """Read the sk from a DB row, preferring the encrypted column.

    Falls back to the legacy plaintext column when the encrypted
    column is empty (pre-migration rows). The caller is expected to
    have the right key in the env; a wrong key bubbles up as
    ``SecretDecryptionError`` from the dispatcher's secret endpoint,
    which is the only place the plaintext is supposed to leave the
    server.
    """
    if "sk_ciphertext" in row.keys():
        stored = row["sk_ciphertext"] or ""
        if stored:
            try:
                return decrypt_secret(stored)
            except Exception:  # noqa: BLE001 - legacy fallback
                pass
    return (row["sk"] or "") if "sk" in row.keys() else ""


def _compute_warnings(worker_type: str, api_key_env: str) -> list[str]:
    warning = auth_env_warning(worker_type, api_key_env)
    return [warning] if warning else []


def _replace_profile_models(conn: sqlite3.Connection, profile_id: str, default_model: str, models: Iterable[str], now: str) -> None:
    values = [item.strip() for item in (default_model, *models) if item and item.strip()]
    values = list(dict.fromkeys(values))
    conn.execute(
        "DELETE FROM ai_profile_models WHERE profile_id = ?",
        (profile_id,),
    )
    for model in values:
        conn.execute(
            """
            INSERT OR REPLACE INTO ai_profile_models (profile_id, model, updated_at)
            VALUES (?, ?, ?)
            """,
            (profile_id, model, now),
        )


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
        rows = conn.execute(_profile_select_sql()).fetchall()
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
                healthcheck_timeout, model_reasoning_effort, sk, sk_ciphertext,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pid, body.name, body.description, body.worker_type,
                body.provider, body.base_url, body.model, body.api_key_env,
                1 if body.available else 0, body.detail,
                body.healthcheck_timeout, body.model_reasoning_effort,
                # Legacy plaintext column is left empty: read path
                # always uses the encrypted column.
                "",
                encrypt_secret((body.sk or "").strip()),
                now, now,
            ),
        )
        _replace_profile_models(conn, pid, body.model, body.models, now)
        row = conn.execute(_profile_select_sql("p.id = ?", "p.id"), (pid,)).fetchone()
    profile = _row_to_profile(row)
    dump = profile.model_dump()
    dump["sk"] = profile.sk  # exclude=True stripped it; restore for re-wrap
    return AiProfileWithHealth(
        **dump,
        health=HealthCheckResult(ok=True, checks=[]),
    )


@router.get("/ai-profiles/{profile_id}", response_model=AiProfile)
def get_ai_profile(profile_id: str):
    with get_conn() as conn:
        row = conn.execute(_profile_select_sql("p.id = ?", "p.id"), (profile_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"ai profile not found: {profile_id}")
    return _row_to_profile(row)


@router.get("/ai-profiles/{profile_id}/secret")
def get_ai_profile_secret(profile_id: str) -> dict[str, str | None]:
    """Return the raw ``sk`` value for a profile. Dispatcher-only.

    The general-purpose ``GET /ai-profiles/{id}`` masks the value behind
    ``sk_set`` / ``sk_preview``; the dispatcher needs the actual token
    at task-launch time to inject it into the worker container env.
    Returns ``{"value": "<sk or null>"}``; ``null`` means the column is
    empty (operator relies on the host env). 404 for unknown ids.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT sk, sk_ciphertext FROM ai_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, f"ai profile not found: {profile_id}")
    # Prefer the encrypted column; on a key-rotation error, surface
    # 503 so the dispatcher can fall back to the host env rather than
    # silently using a stale value.
    sk = _resolve_sk_from_row(row).strip()
    if not sk and row["sk"]:
        # Legacy column had a value but we could not decrypt it.
        try:
            decrypt_secret(row["sk_ciphertext"] or "")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                503,
                f"sk on profile {profile_id} cannot be decrypted; "
                "re-enter the sk on the AI profile settings page",
            ) from exc
    return {"value": sk or None}


@router.put("/ai-profiles/{profile_id}", response_model=AiProfileWithHealth)
def update_ai_profile(profile_id: str, body: AiProfileUpdate):
    with get_conn() as conn:
        row = conn.execute(_profile_select_sql("p.id = ?", "p.id"), (profile_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"ai profile not found: {profile_id}")
        updates: dict[str, object] = {}
        for field in (
            "name", "description", "worker_type", "provider", "base_url",
            "model", "api_key_env", "detail", "healthcheck_timeout",
            "model_reasoning_effort",
        ):
            value = getattr(body, field)
            if value is not None:
                updates[field] = value
        if body.available is not None:
            updates["available"] = 1 if body.available else 0
        if body.sk is not None:
            stripped = body.sk.strip()
            updates["sk"] = stripped
            updates["sk_ciphertext"] = encrypt_secret(stripped)
        if updates:
            updates["updated_at"] = _utcnow()
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [profile_id]
            conn.execute(
                f"UPDATE ai_profiles SET {set_clause} WHERE id = ?",
                values,
            )
        if body.models is not None:
            next_model = str(updates.get("model", row["model"]))
            _replace_profile_models(conn, profile_id, next_model, body.models, _utcnow())
        row = conn.execute(_profile_select_sql("p.id = ?", "p.id"), (profile_id,)).fetchone()
    profile = _row_to_profile(row)
    dump = profile.model_dump()
    dump["sk"] = profile.sk  # exclude=True stripped it; restore for re-wrap
    return AiProfileWithHealth(
        **dump,
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
    ``claudecode``) are dropped silently with a debug log.

    After upserting, any seeded profile whose ``seeded_from_worker`` is
    not present in the current payload is deleted so the catalog mirrors
    ``dispatch.yaml`` exactly. Profiles with ``seeded_from_worker IS
    NULL`` (i.e. operator-created) are never pruned by sync. Snapshots
    in ``project_ai_profiles`` keep their copied fields, so historical
    projects still see the snapshot but the profile id is reported as
    unavailable if it was removed.
    """
    supported = {"codex", "claudecode"}
    now = _utcnow()
    accepted: list[str] = []
    dropped: list[tuple[str, str]] = []
    active_worker_names: set[str] = set()
    with with_immediate_tx() as conn:
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
            # Dispatcher already resolved the token from its host env; we
            # capture it on insert. On update, only overwrite sk when the
            # payload carries a non-empty value, so a re-sync that ran
            # without the env var set never wipes a key the operator
            # typed into the Add/Edit form.
            sk_value = (worker.sk or "").strip()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO ai_profiles (
                        id, name, description, worker_type, provider, base_url,
                        model, api_key_env, available, detail,
                        healthcheck_timeout, model_reasoning_effort, seeded_from_worker, sk, sk_ciphertext,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 1.0, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile_id, worker.name, "",
                        worker.worker_type, worker.provider, worker.base_url,
                        worker.model, worker.api_key_env, "",
                        worker.model_reasoning_effort, worker.name, "",
                        encrypt_secret(sk_value), now, now,
                    ),
                )
                target_profile_id = profile_id
            else:
                if sk_value:
                    conn.execute(
                        """
                        UPDATE ai_profiles SET
                            name = ?, worker_type = ?, provider = ?, base_url = ?,
                            model = ?, api_key_env = ?, available = 1,
                            model_reasoning_effort = ?, seeded_from_worker = ?,
                            sk = ?, sk_ciphertext = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            worker.name, worker.worker_type, worker.provider,
                            worker.base_url, worker.model, worker.api_key_env,
                            worker.model_reasoning_effort, worker.name,
                            "", encrypt_secret(sk_value), now, existing["id"],
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE ai_profiles SET
                            name = ?, worker_type = ?, provider = ?, base_url = ?,
                            model = ?, api_key_env = ?, available = 1,
                            model_reasoning_effort = ?, seeded_from_worker = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            worker.name, worker.worker_type, worker.provider,
                            worker.base_url, worker.model, worker.api_key_env,
                            worker.model_reasoning_effort, worker.name, now, existing["id"],
                        ),
                    )
                target_profile_id = existing["id"]
            _replace_profile_models(conn, target_profile_id, worker.model, worker.models, now)
            accepted.append(worker.name)
            active_worker_names.add(worker.name)

        # Prune seeded profiles that no longer match the active worker set.
        # ai_profile_models rows are removed via ON DELETE CASCADE on the FK;
        # the explicit DELETE is a defensive belt-and-suspenders step in
        # case the FK is ever weakened. We do NOT touch profiles with
        # seeded_from_worker IS NULL (operator-created profiles).
        _prune_orphaned_seeded_profiles(conn, active_worker_names)

        conn.commit()
    for name, reason in dropped:
        import logging
        logging.getLogger(__name__).info(
            "ai_profile sync dropped worker=%s reason=%s", name, reason,
        )
    return list_ai_profiles_with_health()


def _prune_orphaned_seeded_profiles(
    conn: sqlite3.Connection,
    active_worker_names: set[str],
) -> int:
    """Delete seeded profiles whose worker is no longer in ``dispatch.yaml``.

    Returns the number of profile rows removed. Profiles with
    ``seeded_from_worker IS NULL`` (operator-created) are never touched.
    Snapshots in ``project_ai_profiles`` store copied fields, so deleting
    a profile leaves historical project references intact but they will
    be reported as ``unavailable`` by ``get_project_ai_profiles``.
    """
    if active_worker_names:
        placeholders = ",".join("?" for _ in active_worker_names)
        params: tuple[str, ...] = tuple(active_worker_names)
        conn.execute(
            f"""
            DELETE FROM ai_profile_models
            WHERE profile_id IN (
                SELECT id FROM ai_profiles
                WHERE seeded_from_worker IS NOT NULL
                  AND seeded_from_worker NOT IN ({placeholders})
            )
            """,
            params,
        )
        cursor = conn.execute(
            f"""
            DELETE FROM ai_profiles
            WHERE seeded_from_worker IS NOT NULL
              AND seeded_from_worker NOT IN ({placeholders})
            """,
            params,
        )
        return cursor.rowcount
    # No active workers: drop every seeded profile and its models.
    conn.execute(
        "DELETE FROM ai_profile_models "
        "WHERE profile_id IN (SELECT id FROM ai_profiles WHERE seeded_from_worker IS NOT NULL)"
    )
    cursor = conn.execute("DELETE FROM ai_profiles WHERE seeded_from_worker IS NOT NULL")
    return cursor.rowcount


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


@router.post("/ai-profiles/models-report", status_code=204)
def post_models_report(body: AiProfileModelsReportRequest):
    """Dispatcher-side model list observations, cached for project creation."""
    if not body.reports:
        return None
    now = _utcnow()
    with get_conn() as conn:
        for report in body.reports:
            row = conn.execute(
                "SELECT id, model FROM ai_profiles WHERE id = ?",
                (report.profile_id,),
            ).fetchone()
            if row is None:
                continue
            if report.error and not report.models:
                conn.execute(
                    """
                    UPDATE ai_profiles
                    SET last_health_message = ?, last_health_at = ?
                    WHERE id = ?
                    """,
                    (f"model list: {report.error}", now, report.profile_id),
                )
                continue
            _replace_profile_models(conn, report.profile_id, row["model"], report.models or [row["model"]], now)
            if report.error:
                conn.execute(
                    """
                    UPDATE ai_profiles
                    SET last_health_message = ?, last_health_at = ?
                    WHERE id = ?
                    """,
                    (f"model list: {report.error}", now, report.profile_id),
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
        rows = conn.execute(_profile_select_sql()).fetchall()
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
        dump = profile.model_dump()
        dump["sk"] = profile.sk  # exclude=True stripped it; restore
        result.append(AiProfileWithHealth(
            **dump,
            health=HealthCheckResult(ok=ok, checks=checks),
        ))
    return result


# ---------------------------------------------------------------------------
# Project snapshot helpers (unchanged)
# ---------------------------------------------------------------------------


def _load_snapshots(conn: sqlite3.Connection, project_id: str) -> list[ProjectAiProfileSnapshot]:
    rows = conn.execute(
        """
        SELECT profile_id, task_type, role, position,
               snapshot_name, snapshot_worker_type, snapshot_provider,
               snapshot_base_url, snapshot_model, snapshot_reasoning_type,
               snapshot_api_key_env
        FROM project_ai_profiles
        WHERE project_id = ?
        ORDER BY task_type, role, position
        """,
        (project_id,),
    ).fetchall()
    return [
        ProjectAiProfileSnapshot(
            profile_id=row["profile_id"],
            task_type=row["task_type"],
            role=row["role"],
            position=row["position"],
            snapshot_name=row["snapshot_name"],
            snapshot_worker_type=row["snapshot_worker_type"],
            snapshot_provider=row["snapshot_provider"],
            snapshot_base_url=row["snapshot_base_url"],
            snapshot_model=row["snapshot_model"],
            snapshot_reasoning_type=row["snapshot_reasoning_type"] if "snapshot_reasoning_type" in row.keys() else None,
            snapshot_api_key_env=row["snapshot_api_key_env"],
        )
        for row in rows
    ]


def _selection_from_snapshots(snapshots: Iterable[ProjectAiProfileSnapshot]) -> AiProfileSelection:
    primary: str | None = None
    primary_model: str | None = None
    primary_reasoning_type: str | None = None
    fallback: list[str] = []
    for snap in snapshots:
        if snap.role == "primary" and primary is None:
            primary = snap.profile_id
            primary_model = snap.snapshot_model
            primary_reasoning_type = snap.snapshot_reasoning_type
        elif snap.role == "fallback":
            fallback.append(snap.profile_id)
    return AiProfileSelection(
        primary_profile_id=primary,
        primary_model=primary_model,
        primary_reasoning_type=primary_reasoning_type,
        fallback_profile_ids=fallback,
    )


def _profile_models(conn: sqlite3.Connection, profile: sqlite3.Row) -> list[str]:
    rows = conn.execute(
        "SELECT model FROM ai_profile_models WHERE profile_id = ? ORDER BY model",
        (profile["id"],),
    ).fetchall()
    models = [row["model"] for row in rows]
    if profile["model"] and profile["model"] not in models:
        models.insert(0, profile["model"])
    return models or [profile["model"]]


def _selected_reasoning_type(profile: sqlite3.Row) -> str | None:
    return profile["model_reasoning_effort"] if "model_reasoning_effort" in profile.keys() else None


def _selected_model(conn: sqlite3.Connection, profile: sqlite3.Row, selection: AiProfileSelection) -> str:
    model = selection.primary_model or profile["model"]
    allowed = set(_profile_models(conn, profile))
    if model not in allowed:
        raise HTTPException(
            400,
            f"primary_model {model!r} is not available for ai profile {profile['id']}",
        )
    return model


def _task_selections_from_snapshots(snapshots: list[ProjectAiProfileSnapshot]) -> TaskAiProfileSelections:
    by_task = {
        task_type: [snap for snap in snapshots if snap.task_type == task_type]
        for task_type in ("bootstrap", "explore", "reason")
    }
    legacy = [snap for snap in snapshots if snap.task_type == "legacy"]
    return TaskAiProfileSelections(
        bootstrap=_selection_from_snapshots(by_task["bootstrap"] or legacy),
        explore=_selection_from_snapshots(by_task["explore"] or legacy),
        reason=_selection_from_snapshots(by_task["reason"] or legacy),
    )


@router.get("/projects/{project_id}/ai-profiles", response_model=ProjectAiProfilesResponse)
def get_project_ai_profiles(project_id: str):
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
            raise HTTPException(404, f"project not found: {project_id}")
        catalog = [
            _row_to_profile(row)
            for row in conn.execute(_profile_select_sql(order_by="p.id")).fetchall()
        ]
        snapshots = _load_snapshots(conn, project_id)
        selections = _task_selections_from_snapshots(snapshots)
        selection = selections.explore
        available_ids = {item.id for item in catalog if item.available}
        unavailable = sorted({
            snap.profile_id for snap in snapshots
            if snap.profile_id not in available_ids
        })
        return ProjectAiProfilesResponse(
            catalog=catalog,
            selection=selection,
            selections=selections,
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
    persist_project_ai_selections(
        conn,
        project_id,
        TaskAiProfileSelections(
            bootstrap=selection,
            explore=selection,
            reason=selection,
        ),
        now,
        task_types=("legacy",),
    )


def persist_project_ai_selections(
    conn: sqlite3.Connection,
    project_id: str,
    selections: TaskAiProfileSelections,
    now: str,
    *,
    task_types: tuple[str, ...] = ("bootstrap", "explore", "reason"),
) -> None:
    """Store task-specific AI profile snapshots for a project."""
    selection_by_task = {
        "bootstrap": selections.bootstrap,
        "explore": selections.explore,
        "reason": selections.reason,
        "legacy": selections.explore,
    }
    referenced: list[str] = []
    for task_type in task_types:
        selection = selection_by_task[task_type]
        if selection.primary_profile_id:
            referenced.append(selection.primary_profile_id)
        referenced.extend(selection.fallback_profile_ids)
    referenced = list(dict.fromkeys(referenced))
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
    for task_type in task_types:
        selection = selection_by_task[task_type]
        if selection.primary_profile_id:
            profile = by_id[selection.primary_profile_id]
            conn.execute(
                """
                INSERT OR REPLACE INTO project_ai_profiles (
                    project_id, profile_id, task_type, role, position,
                    snapshot_name, snapshot_worker_type, snapshot_provider,
                    snapshot_base_url, snapshot_model, snapshot_reasoning_type,
                    snapshot_api_key_env,
                    created_at
                ) VALUES (?, ?, ?, 'primary', 0, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id, selection.primary_profile_id, task_type,
                    profile["name"], profile["worker_type"], profile["provider"],
                    profile["base_url"],
                    _selected_model(conn, profile, selection),
                    selection.primary_reasoning_type or _selected_reasoning_type(profile),
                    profile["api_key_env"], now,
                ),
            )
        for position, profile_id in enumerate(selection.fallback_profile_ids):
            if profile_id == selection.primary_profile_id:
                continue
            profile = by_id[profile_id]
            conn.execute(
                """
                INSERT OR REPLACE INTO project_ai_profiles (
                    project_id, profile_id, task_type, role, position,
                    snapshot_name, snapshot_worker_type, snapshot_provider,
                    snapshot_base_url, snapshot_model, snapshot_reasoning_type,
                    snapshot_api_key_env,
                    created_at
                ) VALUES (?, ?, ?, 'fallback', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id, profile_id, task_type, position,
                    profile["name"], profile["worker_type"], profile["provider"],
                    profile["base_url"], profile["model"],
                    _selected_reasoning_type(profile),
                    profile["api_key_env"], now,
                ),
            )


def require_complete_ai_profile_selections(selections: TaskAiProfileSelections | None) -> TaskAiProfileSelections:
    if selections is None:
        raise HTTPException(400, "ai_profile_selections is required")
    missing = [
        field
        for task_type in ("bootstrap", "explore", "reason")
        for field, value in (
            (f"{task_type}.primary_profile_id", getattr(selections, task_type).primary_profile_id),
            (f"{task_type}.primary_model", getattr(selections, task_type).primary_model),
            (f"{task_type}.primary_reasoning_type", getattr(selections, task_type).primary_reasoning_type),
        )
        if not value
    ]
    if missing:
        raise HTTPException(
            400,
            f"ai_profile_selections missing required fields: {', '.join(missing)}",
        )
    return selections
