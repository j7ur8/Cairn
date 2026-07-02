from __future__ import annotations

from fastapi import HTTPException

from cairn.server.config.ai_profiles import list_yaml_ai_profiles
from cairn.server.schemas.ai_profiles import (
    AiProfileSelection,
    TaskAiProfileSelections,
    ai_selections_from_snapshots,
)
from cairn.shared.contracts import (
    AiProfile,
    ProjectAiProfileSnapshot,
    ReasoningType,
    canonical_auth_env,
)
from cairn.shared.task_types import builtin_task_type_names


def task_ai_selections_from_snapshots(
    snapshots: list[ProjectAiProfileSnapshot],
) -> TaskAiProfileSelections:
    return ai_selections_from_snapshots(snapshots)


def ai_snapshots_from_selections(
    selections: TaskAiProfileSelections,
    *,
    task_types: tuple[str, ...] = builtin_task_type_names(),
) -> list[ProjectAiProfileSnapshot]:
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
    by_id = {profile.id: profile for profile in list_yaml_ai_profiles()}
    missing = [pid for pid in referenced if pid not in by_id]
    if missing:
        raise HTTPException(400, f"ai profile ids not found: {', '.join(missing)}")
    unavailable = [pid for pid in referenced if not by_id[pid].available]
    if unavailable:
        raise HTTPException(400, f"ai profile ids unavailable: {', '.join(unavailable)}")

    snapshots: list[ProjectAiProfileSnapshot] = []
    for task_type in task_types:
        selection = selection_by_task[task_type]
        if selection.primary_profile_id:
            profile = by_id[selection.primary_profile_id]
            snapshots.append(
                ProjectAiProfileSnapshot(
                    profile_id=selection.primary_profile_id,
                    task_type=task_type,
                    role="primary",
                    position=0,
                    snapshot_name=profile.name,
                    snapshot_worker_type=profile.worker_type,
                    snapshot_provider=profile.provider,
                    snapshot_base_url=profile.base_url,
                    snapshot_model=_selected_model(profile, selection),
                    snapshot_reasoning_type=selection.primary_reasoning_type or _selected_reasoning_type(profile),
                    snapshot_api_key_env=_normalized_api_key_env(profile.worker_type, profile.api_key_env),
                    snapshot_api_key_value=profile.sk,
                )
            )
        for position, profile_id in enumerate(selection.fallback_profile_ids):
            if profile_id == selection.primary_profile_id:
                continue
            profile = by_id[profile_id]
            snapshots.append(
                ProjectAiProfileSnapshot(
                    profile_id=profile_id,
                    task_type=task_type,
                    role="fallback",
                    position=position,
                    snapshot_name=profile.name,
                    snapshot_worker_type=profile.worker_type,
                    snapshot_provider=profile.provider,
                    snapshot_base_url=profile.base_url,
                    snapshot_model=profile.model,
                    snapshot_reasoning_type=_selected_reasoning_type(profile),
                    snapshot_api_key_env=_normalized_api_key_env(profile.worker_type, profile.api_key_env),
                    snapshot_api_key_value=profile.sk,
                )
            )
    return snapshots


def require_complete_ai_profile_selections(
    selections: TaskAiProfileSelections | None,
) -> TaskAiProfileSelections:
    if selections is None:
        raise HTTPException(400, "ai_profiles is required")
    missing = [
        field
        for task_type in builtin_task_type_names()
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


def _profile_models(profile: AiProfile) -> list[str]:
    models = list(profile.models)
    if profile.model and profile.model not in models:
        models.insert(0, profile.model)
    return models or [profile.model]


def _selected_reasoning_type(profile: AiProfile) -> ReasoningType | None:
    return profile.model_reasoning_effort


def _selected_model(
    profile: AiProfile,
    selection: AiProfileSelection,
) -> str:
    model = selection.primary_model or profile.model
    allowed = set(_profile_models(profile))
    if model not in allowed:
        raise HTTPException(
            400,
            f"primary_model {model!r} is not available for ai profile {profile.id}",
        )
    return model


def _normalized_api_key_env(worker_type: str, api_key_env: str | None = None) -> str:
    return canonical_auth_env(worker_type) or (api_key_env or "").strip()
