from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from cairn.shared.task_types import TASK_TYPE_REGISTRY, builtin_task_type_names

CapabilitySource = Literal["builtin", "user"]


class CapabilityHealthEntry(BaseModel):
    capability_id: str
    status: Literal["ok", "warn", "error"]
    message: str = ""


class TaskCapabilities(BaseModel):
    mcp_server_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    user_mcp_server_ids: list[str] = Field(default_factory=list)
    user_skill_ids: list[str] = Field(default_factory=list)
    role_default_skill_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _dedupe(self) -> TaskCapabilities:
        for field in ("mcp_server_ids", "skill_ids", "user_mcp_server_ids", "user_skill_ids", "role_default_skill_ids"):
            value = getattr(self, field) or []
            seen: set[str] = set()
            deduped: list[str] = []
            for item in value:
                key = (item or "").strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                deduped.append(key)
            setattr(self, field, deduped)
        return self


TaskCapabilitiesMap = dict[str, TaskCapabilities]


def task_capabilities_map(values: dict[str, dict[str, list[str]]] | None) -> TaskCapabilitiesMap:
    out: TaskCapabilitiesMap = {}
    for task in builtin_task_type_names():
        payload = values.get(task) if isinstance(values, dict) else None
        if payload is None:
            payload = {}
        out[task] = TaskCapabilities(
            mcp_server_ids=list(payload.get("mcp_server_ids") or []),
            skill_ids=list(payload.get("skill_ids") or []),
            user_mcp_server_ids=list(payload.get("user_mcp_server_ids") or []),
            user_skill_ids=list(payload.get("user_skill_ids") or []),
            role_default_skill_ids=list(payload.get("role_default_skill_ids") or []),
        )
    return out


class CapabilityCatalogItem(BaseModel):
    id: str
    name: str
    kind: Literal["mcp_server", "skill"]
    description: str = ""
    task_types: list[str] = Field(default_factory=list)
    requires_ids: list[str] = Field(default_factory=list)
    required_skill_ids: list[str] = Field(default_factory=list)
    use_when: list[str] = Field(default_factory=list)
    activation_hint: str = ""
    preferred_mcp_ids: list[str] = Field(default_factory=list)
    source: CapabilitySource = "builtin"
    probe_config: dict = Field(default_factory=dict)
    available: bool = True
    detail: str = ""
    source_path: str | None = None
    transport: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    last_probe_status: Literal["ok", "warn", "error"] | None = None
    last_probe_at: str | None = None
    last_probe_message: str = ""

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
        seen: set[str] = set()
        deduped: list[str] = []
        for v in value:
            if v in seen:
                continue
            seen.add(v)
            deduped.append(v)
        return deduped

    @field_validator("requires_ids", "required_skill_ids", "use_when", "preferred_mcp_ids")
    @classmethod
    def validate_string_lists(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in value or []:
            key = (item or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped

    @field_validator("activation_hint")
    @classmethod
    def validate_activation_hint(cls, value: str) -> str:
        return (value or "").strip()


class RoleCatalogItem(BaseModel):
    id: str
    name: str
    description: str = ""
    task_types: list[str] = Field(default_factory=list)
    default_skill_ids: list[str] = Field(default_factory=list)
    available: bool = True
    prompt_sha256: str = ""
    detail: str = ""

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
        seen: set[str] = set()
        deduped: list[str] = []
        for v in value:
            if v in seen:
                continue
            seen.add(v)
            deduped.append(v)
        return deduped

    @field_validator("default_skill_ids")
    @classmethod
    def validate_default_skill_ids(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in value or []:
            key = (item or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped


class ProjectRole(BaseModel):
    project_id: str
    role_id: str
    role_name: str
    role_prompt: str
    role_prompt_sha256: str
    created_at: str


class ProjectRoleResponse(BaseModel):
    role: ProjectRole | None = None
