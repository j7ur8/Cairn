from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from cairn.dispatcher.prompts.layout import PROMPT_PHASES, role_prompt_path
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
        prompts_by_phase = role_prompts_by_phase(role)
        prompt_sha256_by_phase = {
            phase: _sha256(prompt)
            for phase, prompt in prompts_by_phase.items()
        }
        prompt = prompts_by_phase.get("reason", "")
        payload.append(
            {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "task_types": role.task_types,
                "default_skill_ids": list(role.default_skill_ids),
                "available": role.available,
                "prompt": prompt,
                "detail": f"sha256:{_sha256(prompt)}",
                "prompts_by_phase": prompts_by_phase,
                "prompt_sha256_by_phase": prompt_sha256_by_phase,
            }
        )
    return payload


def role_prompts_by_phase(role: RoleConfig) -> dict[str, str]:
    prompts: dict[str, str] = {}
    for phase in PROMPT_PHASES:
        try:
            prompt = role_prompt_path(phase, role.id).read_text(encoding="utf-8").strip()
        except FileNotFoundError as exc:
            raise ValueError(f"role {role.id} missing {phase} role prompt") from exc
        if not prompt:
            raise ValueError(f"role {role.id} {phase} role prompt is empty")
        prompts[phase] = prompt
    return prompts


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
    prompts_by_phase = role.get("prompts_by_phase") if isinstance(role.get("prompts_by_phase"), dict) else {}
    prompt_sha256_by_phase = (
        role.get("prompt_sha256_by_phase") if isinstance(role.get("prompt_sha256_by_phase"), dict) else {}
    )
    role_prompt_text = _string_value(prompts_by_phase.get(task_type))
    role_hash = _string_value(prompt_sha256_by_phase.get(task_type))
    errors: list[str] = []
    if task_type not in PROMPT_PHASES:
        errors.append(f"project:{project_id}: invalid role phase {task_type}")
        return RoleInjection("", _summary(role_id, role_hash, errors), role_id=role_id, errors=errors)
    if not role_id:
        errors.append(f"project:{project_id}: invalid role snapshot")
        return RoleInjection("", _summary(None, None, errors), errors=errors)
    if not role_prompt_text:
        errors.append(f"project:{project_id}: missing {task_type} role prompt for {role_id}")
        return RoleInjection("", _summary(role_id, role_hash, errors), role_id=role_id, errors=errors)
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
