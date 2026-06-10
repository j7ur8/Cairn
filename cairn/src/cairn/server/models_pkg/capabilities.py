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
    role_default_skill_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _dedupe(self) -> "TaskCapabilities":
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
    """Build a per-task map with empty defaults when the caller omits a stage."""
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
    # MCP-only: skills the agent must load alongside this MCP. Mirrors
    # ``requires_ids`` (skill-only) but in the opposite direction: an
    # MCP declares which skills it needs. The expansion layer uses this
    # to auto-inject ``source="required"`` snapshot rows. Empty for
    # ``kind = "skill"``; the server rejects writes that try to set it.
    required_skill_ids: list[str] = Field(default_factory=list)
    # Dynamic routing metadata for prompt injection. These fields are
    # generic declarations rendered by dispatcher/capabilities.py; the
    # Python code must not hardcode skill- or MCP-specific usage rules.
    use_when: list[str] = Field(default_factory=list)
    activation_hint: str = ""
    preferred_mcp_ids: list[str] = Field(default_factory=list)
    source: CapabilitySource = "builtin"
    probe_config: dict = Field(default_factory=dict)
    available: bool = True
    detail: str = ""
    # Mirror the admin write fields so the Settings UI can show and
    # edit a row's current configuration without a second round-trip.
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

    @field_validator("required_skill_ids")
    @classmethod
    def validate_required_skill_ids(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in value or []:
            key = (item or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped

    @field_validator("use_when", "preferred_mcp_ids")
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


class CapabilityAdminRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    task_types: list[str] = Field(default_factory=list)
    requires_ids: list[str] = Field(default_factory=list)
    # MCP-only: skills to auto-inject alongside this MCP. Validated as a
    # catalog-existence + kind check on the server side; clients can
    # write it but the server rejects unknown ids with HTTP 400.
    required_skill_ids: list[str] = Field(default_factory=list)
    use_when: list[str] = Field(default_factory=list)
    activation_hint: str = ""
    preferred_mcp_ids: list[str] = Field(default_factory=list)
    probe_config: dict = Field(default_factory=dict)
    detail: str = ""
    available: bool = True
    source_path: str | None = None
    transport: str | None = None  # mcp_server only
    command: str | None = None  # mcp_server stdio only
    args: list[str] = Field(default_factory=list)  # mcp_server stdio only
    url: str | None = None  # mcp_server http only
    headers: dict[str, str] = Field(default_factory=dict)  # mcp_server http only


class CapabilityAdminResponse(BaseModel):
    catalog: list[CapabilityCatalogItem]
    health: dict[str, list[CapabilityHealthEntry]] = Field(default_factory=dict)


class CapabilitySelection(BaseModel):
    """User-selected capabilities for one task type."""

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


TaskCapabilitySelectionMap = dict[str, CapabilitySelection]


def task_capability_selection_map(
    values: dict[str, dict[str, list[str]]] | dict[str, CapabilitySelection] | None,
) -> TaskCapabilitySelectionMap:
    out: TaskCapabilitySelectionMap = {}
    for task in builtin_task_type_names():
        payload = values.get(task) if isinstance(values, dict) else None
        if isinstance(payload, CapabilitySelection):
            out[task] = payload
        elif isinstance(payload, dict):
            out[task] = CapabilitySelection(
                mcp_server_ids=list(payload.get("mcp_server_ids") or []),
                skill_ids=list(payload.get("skill_ids") or []),
            )
        else:
            out[task] = CapabilitySelection()
    return out


class ProjectCapabilitySnapshotItem(BaseModel):
    kind: Literal["mcp_server", "skill"]
    capability_id: str
    source: Literal["selected", "required", "role_default"]


class ProjectCapabilityTaskState(BaseModel):
    selected: CapabilitySelection = Field(default_factory=CapabilitySelection)
    snapshots: list[ProjectCapabilitySnapshotItem] = Field(default_factory=list)


class ProjectCapabilitiesResponse(BaseModel):
    catalog: list[CapabilityCatalogItem]
    tasks: dict[str, ProjectCapabilityTaskState] = Field(default_factory=dict)
    health: dict[str, list[CapabilityHealthEntry]] = Field(default_factory=dict)
    unavailable: dict[str, list[str]] = Field(default_factory=dict)


class ProjectCapabilitiesUpdateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    capabilities: TaskCapabilitySelectionMap



class RoleCatalogItem(BaseModel):
    id: str
    name: str
    description: str = ""
    task_types: list[str] = Field(default_factory=list)
    default_skill_ids: list[str] = Field(default_factory=list)

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
    available: bool = True
    prompt_sha256: str = ""
    detail: str = ""


class ProjectRole(BaseModel):
    project_id: str
    role_id: str
    role_name: str
    role_prompt: str
    role_prompt_sha256: str
    created_at: str


class ProjectRoleResponse(BaseModel):
    role: ProjectRole | None = None
