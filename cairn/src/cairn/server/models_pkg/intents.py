from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from cairn.server.models_pkg.ai_profiles import AiProfileSelection, TaskAiProfileSelections
from cairn.server.models_pkg.capabilities import (  # noqa: F401
    CapabilitySelection,
    TaskCapabilitySelectionMap,
    TaskCapabilitiesMap,
    task_capability_selection_map,
    task_capabilities_map,
)
from cairn.server.models_pkg.projects import (
    CreateHintInline,
    Fact,
    Intent,
    LLM_EVENT_KIND_OPTIONS,
    ProjectDetail,
    ProjectMeta,
    normalize_llm_event_kinds,
)

class CreateProjectRequest(BaseModel):
    model_config = {"extra": "forbid"}

    title: str
    origin: str
    goal: str
    hints: list[CreateHintInline] | None = None
    capabilities: TaskCapabilitySelectionMap | None = None
    role_id: str | None = None
    proxy_id: str | None = None
    ai_profiles: TaskAiProfileSelections | None = None
    llm_visible_event_kinds: list[str] | None = None

    @model_validator(mode="after")
    def _normalize_defaults(self) -> "CreateProjectRequest":
        if self.capabilities is None:
            self.capabilities = task_capability_selection_map(None)
        if self.llm_visible_event_kinds is None:
            self.llm_visible_event_kinds = list(LLM_EVENT_KIND_OPTIONS)
            self.llm_visible_event_kinds.remove("usage")
        return self

    @field_validator("llm_visible_event_kinds")
    @classmethod
    def validate_llm_visible_event_kinds(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return normalize_llm_event_kinds(value)

    @field_validator("title", "origin", "goal", "role_id")
    @classmethod
    def validate_non_empty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class CreateHintRequest(BaseModel):
    content: str
    creator: str

    @field_validator("content", "creator")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class CreateIntentRequest(BaseModel):
    from_: list[str] = Field(alias="from", min_length=1)
    description: str
    creator: str
    worker: str | None = None

    model_config = {"populate_by_name": True}

    @field_validator("description", "creator", "worker")
    @classmethod
    def validate_non_empty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("from_")
    @classmethod
    def validate_fact_ids(cls, value: list[str]) -> list[str]:
        cleaned = []
        for item in value:
            text = item.strip()
            if not text:
                raise ValueError("fact ids must not be empty")
            cleaned.append(text)
        return cleaned


class HeartbeatRequest(BaseModel):
    worker: str
    run_id: str | None = None

    @field_validator("worker", "run_id")
    @classmethod
    def validate_non_empty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class ReasonClaimRequest(BaseModel):
    worker: str
    trigger: str
    run_id: str | None = None
    trigger_hash: str | None = None
    fact_count: int = Field(ge=0)
    hint_count: int = Field(ge=0)
    open_intent_count: int = Field(ge=0)

    @field_validator("worker", "trigger", "run_id", "trigger_hash")
    @classmethod
    def validate_non_empty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class ReasonFinishRequest(BaseModel):
    worker: str
    run_id: str | None = None
    trigger: str
    trigger_hash: str | None = None
    fact_count: int = Field(ge=0)
    hint_count: int = Field(ge=0)
    open_intent_count: int = Field(ge=0)
    outcome: Literal[
        "success",
        "complete",
        "intents",
        "noop",
        "blocked",
        "failed",
        "timeout",
        "rejected",
        "unhealthy",
        "cancelled",
    ]
    error: str | None = None

    @field_validator("worker", "trigger", "run_id", "trigger_hash")
    @classmethod
    def validate_non_empty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("error")
    @classmethod
    def validate_error(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class ReasonState(BaseModel):
    project_id: str
    trigger: str
    trigger_hash: str
    fact_count: int
    hint_count: int
    open_intent_count: int
    outcome: str
    failure_count: int
    last_error: str
    next_retry_at: str | None = None
    updated_at: str


class ConcludeRequest(BaseModel):
    worker: str
    description: str

    @field_validator("worker", "description")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class CompleteRequest(BaseModel):
    from_: list[str] = Field(alias="from", min_length=1)
    description: str
    worker: str

    model_config = {"populate_by_name": True}

    @field_validator("description", "worker")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("from_")
    @classmethod
    def validate_fact_ids(cls, value: list[str]) -> list[str]:
        cleaned = []
        for item in value:
            text = item.strip()
            if not text:
                raise ValueError("fact ids must not be empty")
            cleaned.append(text)
        return cleaned


class ConcludeResponse(BaseModel):
    fact: Fact
    intent: Intent


class UpdateProjectStatusRequest(BaseModel):
    status: Literal["active", "stopped"]


class UpdateProjectTitleRequest(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class ReopenRequest(BaseModel):
    description: str
    creator: str

    @field_validator("description", "creator")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class ReopenResponse(BaseModel):
    project: ProjectMeta
    fact: Fact
    intent: Intent


class ReplayRunCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    title: str
    origin: str
    goal: str
    hints: list[CreateHintInline] | None = None
    capabilities: TaskCapabilitySelectionMap | None = None
    role_id: str | None = None
    ai_profiles: TaskAiProfileSelections | None = None
    llm_visible_event_kinds: list[str] | None = None

    @field_validator("llm_visible_event_kinds")
    @classmethod
    def validate_llm_visible_event_kinds(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return normalize_llm_event_kinds(value)

    @field_validator("title", "origin", "goal", "role_id")
    @classmethod
    def validate_non_empty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class ReplayRunCreateResponse(BaseModel):
    run_id: str
    source_project_id: str
    project: ProjectDetail


class ReplayRunAdvanceResponse(BaseModel):
    is_replay: bool
    action: Literal["not_replay", "created_intent", "waiting", "completed", "blocked"]
    status: Literal["not_replay", "active", "completed", "blocked"]
    run_id: str | None = None
    project_id: str | None = None
    intent_id: str | None = None
    detail: str | None = None
