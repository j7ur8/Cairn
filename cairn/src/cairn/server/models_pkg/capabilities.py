from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from cairn.server.task_types import TASK_TYPE_REGISTRY



CapabilitySource = Literal["builtin", "user"]


class CapabilityHealthEntry(BaseModel):
    capability_id: str
    status: Literal["ok", "warn", "error"]
    message: str = ""


class TaskCapabilities(BaseModel):
    """Capabilities chosen for a single task_type (bootstrap/explore/reason).

    ``user_mcp_server_ids`` / ``user_skill_ids`` are the literal ids the
    user ticked in the form. ``mcp_server_ids`` / ``skill_ids`` carry the
    full expanded set used by the dispatcher (user picks + requires
    expansion). They are kept on the model so the UI can render the
    ``auto`` badge for sub-skills without re-running the expansion on
    every render.
    """

    mcp_server_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    user_mcp_server_ids: list[str] = Field(default_factory=list)
    user_skill_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _dedupe(self) -> "TaskCapabilities":
        # Always reflect the user picks in the *user_* fields even when the
        # caller only supplied the merged set. This keeps the wire shape
        # consistent for old callers that still send the flat
        # mcp_server_ids/skill_ids only.
        if not self.user_mcp_server_ids and self.mcp_server_ids:
            self.user_mcp_server_ids = list(self.mcp_server_ids)
        if not self.user_skill_ids and self.skill_ids:
            self.user_skill_ids = list(self.skill_ids)
        for field in ("mcp_server_ids", "skill_ids", "user_mcp_server_ids", "user_skill_ids"):
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
    """Build a per-task map with empty defaults when the caller omits a stage."""
    out: TaskCapabilitiesMap = {}
    for task in ("bootstrap", "explore", "reason"):
        payload = values.get(task) if isinstance(values, dict) else None
        if payload is None:
            payload = {}
        out[task] = TaskCapabilities(
            mcp_server_ids=list(payload.get("mcp_server_ids") or []),
            skill_ids=list(payload.get("skill_ids") or []),
            user_mcp_server_ids=list(payload.get("user_mcp_server_ids") or []),
            user_skill_ids=list(payload.get("user_skill_ids") or []),
        )
    return out


class CapabilityCatalogItem(BaseModel):
    id: str
    name: str
    kind: Literal["mcp_server", "skill"]
    description: str = ""
    task_types: list[str] = Field(default_factory=list)
    requires_ids: list[str] = Field(default_factory=list)
    source: CapabilitySource = "builtin"
    probe_config: dict = Field(default_factory=dict)
    available: bool = True
    detail: str = ""
    # Mirror the admin write fields so the Settings UI can show and
    # edit a row's current configuration without a second round-trip.
    # These fields are optional: the legacy /capabilities/catalog
    # endpoint still returns just the public fields.
    source_path: str | None = None
    transport: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    bearer_token_env: str | None = None
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
        # Dedupe while preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for v in value:
            if v in seen:
                continue
            seen.add(v)
            deduped.append(v)
        return deduped

    @field_validator("requires_ids")
    @classmethod
    def validate_requires_ids(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in value or []:
            key = (item or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped


class CapabilityAdminRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    task_types: list[str] = Field(default_factory=list)
    requires_ids: list[str] = Field(default_factory=list)
    probe_config: dict = Field(default_factory=dict)
    detail: str = ""
    available: bool = True
    source_path: str | None = None
    transport: str | None = None  # mcp_server only
    command: str | None = None  # mcp_server stdio only
    args: list[str] = Field(default_factory=list)  # mcp_server stdio only
    url: str | None = None  # mcp_server http only
    bearer_token_env: str | None = None  # mcp_server http only
    headers: dict[str, str] = Field(default_factory=dict)  # mcp_server http only


class CapabilityAdminResponse(BaseModel):
    catalog: list[CapabilityCatalogItem]
    health: dict[str, list[CapabilityHealthEntry]] = Field(default_factory=dict)


class ProjectCapabilitiesResponse(BaseModel):
    catalog: list[CapabilityCatalogItem]
    per_task: TaskCapabilitiesMap = Field(default_factory=task_capabilities_map)
    legacy: CapabilitySelection | None = None
    health: dict[str, list[CapabilityHealthEntry]] = Field(default_factory=dict)
    unavailable_mcp_server_ids: list[str] = Field(default_factory=list)
    unavailable_skill_ids: list[str] = Field(default_factory=list)


class ProjectCapabilitiesUpdateRequest(BaseModel):
    per_task: TaskCapabilitiesMap



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

class CapabilitySelection(BaseModel):
    """Legacy flat project capability selection.

    Kept around so existing tests and the legacy `capabilities` field
    on CreateProjectRequest can still build. The router now stores
    selections as per-task snapshots and the flat shape is mapped to
    the ``explore`` task on the way in.
    """

    mcp_server_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)

    @field_validator("mcp_server_ids", "skill_ids")
    @classmethod
    def validate_ids(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = (item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned


