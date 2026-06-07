from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator

from cairn.server.task_types import TASK_TYPE_REGISTRY

from cairn.server.models_pkg.intents import CapabilitySelection

class CapabilityCatalogItem(BaseModel):
    id: str
    name: str
    kind: Literal["mcp_server", "skill"]
    description: str = ""
    task_types: list[str] = Field(default_factory=list)

    @field_validator("task_types")
    @classmethod
    def validate_task_types(cls, value: list[str]) -> list[str]:
        if not value:
            return value
        unknown = [v for v in value if not TASK_TYPE_REGISTRY.is_valid(v)]
        if unknown:
            raise ValueError(
                f"unknown task_types: {unknown}; "
                f"known: {', '.join(TASK_TYPE_REGISTRY.names())}"
            )
        # Dedupe while preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for v in value:
            if v in seen:
                continue
            seen.add(v)
            deduped.append(v)
        return deduped
    available: bool = True
    detail: str = ""


class ProjectCapabilitiesResponse(BaseModel):
    catalog: list[CapabilityCatalogItem]
    selection: CapabilitySelection
    unavailable_mcp_server_ids: list[str] = Field(default_factory=list)
    unavailable_skill_ids: list[str] = Field(default_factory=list)


class RegisterCapabilityCatalogRequest(BaseModel):
    catalog: list[CapabilityCatalogItem]


class RoleCatalogItem(BaseModel):
    id: str
    name: str
    description: str = ""
    task_types: list[str] = Field(default_factory=list)

    @field_validator("task_types")
    @classmethod
    def validate_task_types(cls, value: list[str]) -> list[str]:
        if not value:
            return value
        unknown = [v for v in value if not TASK_TYPE_REGISTRY.is_valid(v)]
        if unknown:
            raise ValueError(
                f"unknown task_types: {unknown}; "
                f"known: {', '.join(TASK_TYPE_REGISTRY.names())}"
            )
        # Dedupe while preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for v in value:
            if v in seen:
                continue
            seen.add(v)
            deduped.append(v)
        return deduped
    available: bool = True
    prompt_sha256: str = ""
    detail: str = ""


class RegisterRoleCatalogItem(BaseModel):
    id: str
    name: str
    description: str = ""
    task_types: list[str] = Field(default_factory=list)

    @field_validator("task_types")
    @classmethod
    def validate_task_types(cls, value: list[str]) -> list[str]:
        if not value:
            return value
        unknown = [v for v in value if not TASK_TYPE_REGISTRY.is_valid(v)]
        if unknown:
            raise ValueError(
                f"unknown task_types: {unknown}; "
                f"known: {', '.join(TASK_TYPE_REGISTRY.names())}"
            )
        # Dedupe while preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for v in value:
            if v in seen:
                continue
            seen.add(v)
            deduped.append(v)
        return deduped
    available: bool = True
    prompt: str
    detail: str = ""

    @field_validator("id", "name", "prompt")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class RegisterRoleCatalogRequest(BaseModel):
    roles: list[RegisterRoleCatalogItem]


class ProjectRole(BaseModel):
    project_id: str
    role_id: str
    role_name: str
    role_prompt: str
    role_prompt_sha256: str
    created_at: str


class ProjectRoleResponse(BaseModel):
    role: ProjectRole | None = None

