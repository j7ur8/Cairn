from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cairn.shared.config import DispatchConfig, RoleConfig, TaskType


@dataclass(slots=True)
class RoleInjection:
    instructions: str
    summary: str
    role_id: str | None = None
    role_prompt_sha256: str | None = None
    errors: list[str] | None = None


def catalog_payload(config: DispatchConfig) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for role in config.roles:
        prompt = role_prompt(role)
        payload.append(
            {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "task_types": role.task_types,
                "default_skill_ids": list(role.default_skill_ids),
                "available": True,
                "prompt": prompt,
                "detail": f"sha256:{_sha256(prompt)}",
            }
        )
    return payload


def role_prompt(role: RoleConfig) -> str:
    if role.prompt is not None:
        return role.prompt.strip()
    assert role.source_path is not None
    return Path(role.source_path).read_text(encoding="utf-8").strip()


def inject_project_role(
    project_id: str,
    task_type: TaskType,
    role_data: dict[str, Any] | None,
) -> RoleInjection:
    if not role_data:
        return RoleInjection("", "no project role selected", errors=[])
    role = role_data.get("role") if isinstance(role_data.get("role"), dict) else None
    if not role:
        return RoleInjection("", "no project role selected", errors=[])
    role_id = _string_value(role.get("role_id"))
    role_prompt_text = _string_value(role.get("role_prompt"))
    role_hash = _string_value(role.get("role_prompt_sha256"))
    errors: list[str] = []
    if not role_id or not role_prompt_text:
        errors.append(f"project:{project_id}: invalid role snapshot")
        return RoleInjection("", _summary(None, None, errors), errors=errors)
    instructions = _instructions(role_prompt_text)
    return RoleInjection(
        instructions=instructions,
        summary=_summary(role_id, role_hash, errors),
        role_id=role_id,
        role_prompt_sha256=role_hash,
        errors=errors,
    )


def _instructions(prompt: str) -> str:
    return "\n".join(
        [
            "## Project Type",
            prompt.strip(),
        ]
    )


def _summary(role_id: str | None, role_hash: str | None, errors: list[str]) -> str:
    return json.dumps(
        {"role_id": role_id, "role_prompt_sha256": role_hash, "errors": errors},
        ensure_ascii=False,
        indent=2,
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _string_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
