from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from cairn.server.config.files import _text_sha256, load_resources_data, resources_yaml_path, save_resources_data
from cairn.server.schemas import RoleCatalogItem


def list_yaml_roles() -> list[RoleCatalogItem]:
    data = load_resources_data()
    roles_raw = data.get("roles")
    roles = roles_raw if isinstance(roles_raw, list) else []
    result: list[RoleCatalogItem] = []
    for item in roles:
        payload = dict(item)
        payload.setdefault("available", True)
        payload.setdefault("detail", "")
        payload.setdefault("prompt_sha256", "")
        result.append(RoleCatalogItem.model_validate(payload))
    return result


def update_yaml_role_default_skills(role_id: str, default_skill_ids: list[str]) -> RoleCatalogItem:
    data = load_resources_data()
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
    normalized = _normalize_default_skill_ids(default_skill_ids)
    missing = [skill_id for skill_id in normalized if skill_id not in valid_skill_ids]
    if missing:
        raise HTTPException(400, f"default_skill_ids references unknown skill: {missing[0]}")
    target["default_skill_ids"] = normalized
    save_resources_data(data)
    return next(role for role in list_yaml_roles() if role.id == role_id)


def get_yaml_role_snapshot(role_id: str) -> dict[str, Any] | None:
    data = load_resources_data()
    roles_raw = data.get("roles")
    roles = roles_raw if isinstance(roles_raw, list) else []
    for item in roles:
        if not isinstance(item, dict) or item.get("id") != role_id:
            continue
        prompt = str(item.get("prompt") or "")
        if not prompt and item.get("source_path"):
            path = Path(str(item["source_path"]))
            if not path.is_absolute():
                path = resources_yaml_path().parent / path
            prompt = path.read_text(encoding="utf-8").strip()
        return {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or item.get("id") or ""),
            "prompt": prompt,
            "prompt_sha256": _text_sha256(prompt),
            "default_skill_ids": list(item.get("default_skill_ids") or []),
        }
    return None


def _normalize_default_skill_ids(default_skill_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for item in default_skill_ids or []:
        skill_id = str(item or "").strip()
        if not skill_id or skill_id in seen:
            continue
        seen.add(skill_id)
        normalized.append(skill_id)
    return normalized
