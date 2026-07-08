from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cairn.shared.config.constants import TaskType, _check_known_task_types
from cairn.shared.task_types import builtin_task_type_names


def normalize_default_skill_ids(value: list[str] | None) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in value or []:
        key = str(item or "").strip()
        if not key or key in seen:
            continue
        if any(ch.isspace() for ch in key) or "/" in key or "\\" in key:
            raise ValueError("default_skill_ids must not contain whitespace, '/', or '\\'")
        seen.add(key)
        deduped.append(key)
    return deduped


class RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    task_types: list[TaskType] = Field(default_factory=lambda: list(builtin_task_type_names()))
    description: str = ""
    default_skill_ids: list[str] = Field(default_factory=list)
    detail: str = ""
    available: bool = True

    @field_validator("id", "name")
    @classmethod
    def validate_text(cls, value: str) -> str:
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
        return normalize_default_skill_ids(value)


def prepare_role_data(data: Any, _config_dir: Path) -> Any:
    return data
