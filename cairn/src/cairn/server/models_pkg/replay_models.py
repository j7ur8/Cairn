from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

from cairn.server.models_pkg.ai_profiles import TaskAiProfileSelections
from cairn.server.models_pkg.capability_selection import TaskCapabilitySelectionMap
from cairn.server.models_pkg.projects import CreateHintInline, ProjectDetail, normalize_llm_event_kinds
from cairn.shared.contracts import TaskTimeouts


class ReplayRunCreateRequest(BaseModel):
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
