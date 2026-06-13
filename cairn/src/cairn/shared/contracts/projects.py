from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator

from cairn.shared.contracts.llm_events import (
    DEFAULT_LLM_HIDDEN_EVENT_KINDS,
    normalize_llm_event_kinds,
    visible_kinds_from_hidden,
)
from cairn.shared.contracts.proxies import ProxySummary


class Fact(BaseModel):
    id: str
    description: str


class Intent(BaseModel):
    id: str
    from_: list[str] = Field(alias="from")
    to: str | None = None
    description: str
    creator: str
    worker: str | None = None
    last_heartbeat_at: str | None = None
    created_at: str
    concluded_at: str | None = None

    model_config = {"populate_by_name": True}


class Hint(BaseModel):
    id: str
    content: str
    creator: str
    created_at: str


class ProjectReason(BaseModel):
    worker: str
    run_id: str | None = None
    trigger: str
    started_at: str
    last_heartbeat_at: str


class ProjectMeta(BaseModel):
    id: str
    title: str
    status: Literal["active", "stopped", "completed"]
    created_at: str
    reason: ProjectReason | None = None
    llm_hidden_event_kinds: list[str] = Field(default_factory=lambda: list(DEFAULT_LLM_HIDDEN_EVENT_KINDS))

    @field_validator("llm_hidden_event_kinds")
    @classmethod
    def validate_llm_hidden_event_kinds(cls, value: list[str]) -> list[str]:
        return normalize_llm_event_kinds(value)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def llm_visible_event_kinds(self) -> list[str]:
        return visible_kinds_from_hidden(self.llm_hidden_event_kinds)


class ProjectSummary(ProjectMeta):
    fact_count: int
    intent_count: int
    working_intent_count: int
    unclaimed_intent_count: int
    hint_count: int


class ProjectWorkSummary(ProjectSummary):
    open_intents: list[Intent] = Field(default_factory=list)
    config_version: int = 0


class ProjectDetail(BaseModel):
    project: ProjectMeta
    facts: list[Fact]
    intents: list[Intent]
    hints: list[Hint]
    proxy: ProxySummary | None = None
