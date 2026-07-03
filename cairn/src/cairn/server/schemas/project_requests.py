from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from cairn.server.schemas.ai_profiles import TaskAiProfileSelections
from cairn.server.schemas.capability_selection import TaskCapabilitySelectionMap, task_capability_selection_map
from cairn.server.schemas.projects import CreateHintInline
from cairn.shared.contracts import LLM_EVENT_KIND_OPTIONS, TaskTimeouts, normalize_llm_event_kinds


class CreateProjectRequest(BaseModel):
    model_config = {"extra": "forbid"}

    title: str
    origin: str
    goal: str
    hints: list[CreateHintInline] | None = None
    capabilities: TaskCapabilitySelectionMap | None = None
    role_id: str | None = None
    ai_profiles: TaskAiProfileSelections | None = None
    task_timeouts: TaskTimeouts
    llm_visible_event_kinds: list[str] | None = None

    @model_validator(mode="after")
    def _normalize_defaults(self) -> CreateProjectRequest:
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
