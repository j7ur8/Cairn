from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cairn.shared.config.constants import TaskType, _check_known_task_types
from cairn.shared.task_types import builtin_task_type_names


class RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    task_types: list[TaskType] = Field(default_factory=lambda: list(builtin_task_type_names()))
    description: str = ""
    prompt: str | None = None
    source_path: str | None = None
    default_skill_ids: list[str] = Field(default_factory=list)
    detail: str = ""
    available: bool = True

    @field_validator("id", "name", "prompt", "source_path")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        text = value.strip()
        if any(ch.isspace() for ch in text) or "/" in text or "\\" in text:
            raise ValueError("id must not contain whitespace, '/', or '\\'")
        return text

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("task_types")
    @classmethod
    def validate_task_types(cls, value: list[TaskType]) -> list[TaskType]:
        if not value:
            raise ValueError("task_types must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("task_types must be unique")
        _check_known_task_types(value)
        return value

    @field_validator("default_skill_ids")
    @classmethod
    def validate_default_skill_ids(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in value or []:
            key = (item or "").strip()
            if not key or key in seen:
                continue
            if any(ch.isspace() for ch in key) or "/" in key or "\\" in key:
                raise ValueError("default_skill_ids must not contain whitespace, '/', or '\\'")
            seen.add(key)
            deduped.append(key)
        return deduped

    @model_validator(mode="after")
    def validate_prompt_source(self) -> RoleConfig:
        if bool(self.prompt) == bool(self.source_path):
            raise ValueError(f"role {self.id} must set exactly one of prompt or source_path")
        return self


def prepare_role_data(data: Any, config_dir: Path) -> Any:
    if not isinstance(data, dict):
        return data
    roles = data.get("roles")
    if not isinstance(roles, list):
        return data
    prepared_roles: list[Any] = []
    for role in roles:
        if not isinstance(role, dict):
            prepared_roles.append(role)
            continue
        role_copy = dict(role)
        source_path = role_copy.get("source_path")
        if isinstance(source_path, str):
            path = Path(source_path).expanduser()
            if not path.is_absolute():
                path = config_dir / path
            role_copy["source_path"] = str(path.resolve(strict=False))
        prepared_roles.append(role_copy)
    data_copy = dict(data)
    data_copy["roles"] = prepared_roles
    return data_copy
