from __future__ import annotations

from typing import Any, Iterable

from fastapi import HTTPException

from cairn.server.models import (
    AiProfileSelection,
    ProjectAiProfileSnapshot,
    TaskAiProfileSelections,
    canonical_auth_env,
)


def load_project_ai_snapshots(
    conn: Any,
    project_id: str,
) -> list[ProjectAiProfileSnapshot]:
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


def task_ai_selections_from_snapshots(
    snapshots: list[ProjectAiProfileSnapshot],
) -> TaskAiProfileSelections:
    by_task = {
        task_type: [snap for snap in snapshots if snap.task_type == task_type]
        for task_type in ("bootstrap", "explore", "reason")
    }
    return TaskAiProfileSelections(
        bootstrap=_selection_from_snapshots(by_task["bootstrap"]),
        explore=_selection_from_snapshots(by_task["explore"]),
        reason=_selection_from_snapshots(by_task["reason"]),
    )


def persist_project_ai_selection(
    conn: Any,
    project_id: str,
    selection: AiProfileSelection,
    now: str,
) -> None:
    persist_project_ai_selections(
        conn,
        project_id,
        TaskAiProfileSelections(
            bootstrap=selection,
            explore=selection,
            reason=selection,
        ),
        now,
    )


def persist_project_ai_selections(
    conn: Any,
    project_id: str,
    selections: TaskAiProfileSelections,
    now: str,
    *,
    task_types: tuple[str, ...] = ("bootstrap", "explore", "reason"),
) -> None:
    selection_by_task = {
        "bootstrap": selections.bootstrap,
        "explore": selections.explore,
        "reason": selections.reason,
    }
    referenced: list[str] = []
    for task_type in task_types:
        selection = selection_by_task[task_type]
        if selection.primary_profile_id:
            referenced.append(selection.primary_profile_id)
        referenced.extend(selection.fallback_profile_ids)
    referenced = list(dict.fromkeys(referenced))
    rows = (
        conn.execute(
            f"SELECT * FROM ai_profiles WHERE id IN ({','.join('?' * len(referenced))})",
            referenced,
        ).fetchall()
        if referenced
        else []
    )
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
                INSERT INTO project_ai_profiles (
                    project_id, profile_id, task_type, role, position,
                    snapshot_name, snapshot_worker_type, snapshot_provider,
                    snapshot_base_url, snapshot_model, snapshot_reasoning_type,
                    snapshot_api_key_env,
                    created_at
                ) VALUES (?, ?, ?, 'primary', 0, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    selection.primary_profile_id,
                    task_type,
                    profile["name"],
                    profile["worker_type"],
                    profile["provider"],
                    profile["base_url"],
                    _selected_model(conn, profile, selection),
                    selection.primary_reasoning_type or _selected_reasoning_type(profile),
                    _normalized_api_key_env(profile["worker_type"], profile["api_key_env"]),
                    now,
                ),
            )
        for position, profile_id in enumerate(selection.fallback_profile_ids):
            if profile_id == selection.primary_profile_id:
                continue
            profile = by_id[profile_id]
            conn.execute(
                """
                INSERT INTO project_ai_profiles (
                    project_id, profile_id, task_type, role, position,
                    snapshot_name, snapshot_worker_type, snapshot_provider,
                    snapshot_base_url, snapshot_model, snapshot_reasoning_type,
                    snapshot_api_key_env,
                    created_at
                ) VALUES (?, ?, ?, 'fallback', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    profile_id,
                    task_type,
                    position,
                    profile["name"],
                    profile["worker_type"],
                    profile["provider"],
                    profile["base_url"],
                    profile["model"],
                    _selected_reasoning_type(profile),
                    _normalized_api_key_env(profile["worker_type"], profile["api_key_env"]),
                    now,
                ),
            )


def require_complete_ai_profile_selections(
    selections: TaskAiProfileSelections | None,
) -> TaskAiProfileSelections:
    if selections is None:
        raise HTTPException(400, "ai_profiles is required")
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
            f"ai_profiles missing required fields: {', '.join(missing)}",
        )
    return selections


def _selection_from_snapshots(
    snapshots: Iterable[ProjectAiProfileSnapshot],
) -> AiProfileSelection:
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


def _profile_models(conn: Any, profile: Any) -> list[str]:
    rows = conn.execute(
        "SELECT model FROM ai_profile_models WHERE profile_id = ? ORDER BY model",
        (profile["id"],),
    ).fetchall()
    models = [row["model"] for row in rows]
    if profile["model"] and profile["model"] not in models:
        models.insert(0, profile["model"])
    return models or [profile["model"]]


def _selected_reasoning_type(profile: Any) -> str | None:
    return profile["model_reasoning_effort"] if "model_reasoning_effort" in profile.keys() else None


def _selected_model(
    conn: Any,
    profile: Any,
    selection: AiProfileSelection,
) -> str:
    model = selection.primary_model or profile["model"]
    allowed = set(_profile_models(conn, profile))
    if model not in allowed:
        raise HTTPException(
            400,
            f"primary_model {model!r} is not available for ai profile {profile['id']}",
        )
    return model


def _normalized_api_key_env(worker_type: str, api_key_env: str | None = None) -> str:
    return canonical_auth_env(worker_type) or (api_key_env or "").strip()
