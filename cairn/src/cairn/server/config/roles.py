from __future__ import annotations

from pathlib import Path
from typing import Any

from cairn.server.config.files import _text_sha256, load_resources_data, resources_yaml_path
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
