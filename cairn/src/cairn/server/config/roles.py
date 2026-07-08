from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from cairn.dispatcher.prompts.layout import PROMPT_PHASES, role_prompt_path
from cairn.server.config.files import _text_sha256, load_resources_data, resources_yaml_path, save_resources_data
from cairn.server.schemas import RoleCatalogItem
from cairn.shared.config.role_models import normalize_default_skill_ids


def list_yaml_roles() -> list[RoleCatalogItem]:
    data = load_resources_data()
    roles_raw = data.get("roles")
    roles = roles_raw if isinstance(roles_raw, list) else []
    result: list[RoleCatalogItem] = []
    for item in roles:
        if isinstance(item, dict):
            result.append(RoleCatalogItem.model_validate(_role_catalog_payload(item)))
    return result


def update_yaml_role_default_skills(role_id: str, default_skill_ids: list[str]) -> RoleCatalogItem:
    data = load_resources_data()
    target = set_role_default_skills_in_data(data, role_id, default_skill_ids)
    save_resources_data(data)
    return RoleCatalogItem.model_validate(_role_catalog_payload(target))


def set_role_default_skills_in_data(data: dict[str, Any], role_id: str, default_skill_ids: list[str]) -> dict[str, Any]:
    roles_raw = data.get("roles")
    roles = roles_raw if isinstance(roles_raw, list) else []
    target = next((item for item in roles if isinstance(item, dict) and item.get("id") == role_id), None)
    if target is None:
        raise HTTPException(404, f"role not found: {role_id}")
    caps_raw = data.get("capabilities")
    caps = caps_raw if isinstance(caps_raw, dict) else {}
    skills = caps.get("skills") if isinstance(caps.get("skills"), list) else []
    valid_skill_ids = {
        str(item.get("id") or "").strip()
        for item in skills
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    try:
        normalized = normalize_default_skill_ids(default_skill_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    missing = [skill_id for skill_id in normalized if skill_id not in valid_skill_ids]
    if missing:
        raise HTTPException(400, f"default_skill_ids references unknown skill: {missing[0]}")
    target["default_skill_ids"] = normalized
    return target


def get_yaml_role_snapshot(role_id: str) -> dict[str, Any] | None:
    data = load_resources_data()
    roles_raw = data.get("roles")
    roles = roles_raw if isinstance(roles_raw, list) else []
    for item in roles:
        if not isinstance(item, dict) or item.get("id") != role_id:
            continue
        prompts_by_phase: dict[str, str] = {}
        prompt_sha256_by_phase: dict[str, str] = {}
        for phase in PROMPT_PHASES:
            try:
                prompt = role_prompt_path(phase, role_id).read_text(encoding="utf-8").strip()
            except FileNotFoundError as exc:
                raise ValueError(f"role {role_id} missing {phase} role prompt") from exc
            if not prompt:
                raise ValueError(f"role {role_id} {phase} role prompt is empty")
            prompts_by_phase[phase] = prompt
            prompt_sha256_by_phase[phase] = _text_sha256(prompt)
        prompt = prompts_by_phase.get("reason", "")
        return {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or item.get("id") or ""),
            "prompt": prompt,
            "prompt_sha256": _text_sha256(prompt),
            "prompts_by_phase": prompts_by_phase,
            "prompt_sha256_by_phase": prompt_sha256_by_phase,
            "default_skill_ids": normalize_default_skill_ids(item.get("default_skill_ids") or []),
        }
    return None


def _role_catalog_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    payload.setdefault("available", True)
    role_id = str(payload.get("id") or "").strip()
    if role_id:
        prompt_sha256_by_phase: dict[str, str] = {}
        for phase in PROMPT_PHASES:
            try:
                prompt = role_prompt_path(phase, role_id).read_text(encoding="utf-8").strip()
            except FileNotFoundError as exc:
                raise ValueError(f"role {role_id} missing {phase} role prompt") from exc
            if not prompt:
                raise ValueError(f"role {role_id} {phase} role prompt is empty")
            prompt_sha256_by_phase[phase] = _text_sha256(prompt)
        reason_sha = prompt_sha256_by_phase.get("reason", "")
        payload["prompt_sha256"] = reason_sha
        payload.setdefault("detail", f"sha256:{reason_sha}" if reason_sha else "")
    else:
        payload.setdefault("detail", "")
        payload.setdefault("prompt_sha256", "")
    return payload
