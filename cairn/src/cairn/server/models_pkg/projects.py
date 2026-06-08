from __future__ import annotations

from typing import Literal

import json

from pydantic import BaseModel, Field, computed_field, field_validator

LLM_EVENT_KIND_OPTIONS: tuple[str, ...] = (
    "prompt",
    "stdout",
    "stderr",
    "model_response",
    "parse_error",
    "timeout",
    "cancelled",
    "process_end",
    "result",
    "error",
    "agent_message",
    "thinking",
    "tool_call",
    "tool_result",
    "command_start",
    "command_end",
    "usage",
    "session_init",
    "api_retry",
    "system_event",
    "capability_manifest",
    "trace_parse_error",
)
DEFAULT_LLM_HIDDEN_EVENT_KINDS: tuple[str, ...] = ("usage",)


def normalize_llm_event_kinds(value: list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return list(LLM_EVENT_KIND_OPTIONS)
    allowed = set(LLM_EVENT_KIND_OPTIONS)
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text:
            raise ValueError("event kind must not be empty")
        if text not in allowed:
            raise ValueError(f"unknown event kind: {text}")
        if text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def hidden_kinds_from_visible(value: list[str] | tuple[str, ...] | None) -> list[str]:
    visible = set(normalize_llm_event_kinds(value))
    return [kind for kind in LLM_EVENT_KIND_OPTIONS if kind not in visible]


def visible_kinds_from_hidden(value: list[str] | tuple[str, ...] | None) -> list[str]:
    hidden = set(normalize_llm_event_kinds(value))
    return [kind for kind in LLM_EVENT_KIND_OPTIONS if kind not in hidden]


def parse_llm_hidden_event_kinds(value: str | None) -> list[str]:
    if not value:
        return list(DEFAULT_LLM_HIDDEN_EVENT_KINDS)
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return list(DEFAULT_LLM_HIDDEN_EVENT_KINDS)
    if not isinstance(raw, list):
        return list(DEFAULT_LLM_HIDDEN_EVENT_KINDS)
    try:
        return normalize_llm_event_kinds(raw)
    except ValueError:
        return list(DEFAULT_LLM_HIDDEN_EVENT_KINDS)

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


class AttachmentUpload(BaseModel):
    original_filename: str
    stored_filename: str
    size: int
    path: str
    hint_id: str
    hint: str


class AttachmentUploadResponse(BaseModel):
    project_id: str
    attachments: list[AttachmentUpload]


class ProjectFileItem(BaseModel):
    source: Literal["project", "attachment"]
    path: str
    name: str
    size: int
    modified_at: str
    category: Literal["reports", "exploit", "attachments", "other"]


class ProjectFilesResponse(BaseModel):
    project_id: str
    files: list[ProjectFileItem]


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


class ProjectDetail(BaseModel):
    project: ProjectMeta
    facts: list[Fact]
    intents: list[Intent]
    hints: list[Hint]
    proxy: ProxySummary | None = None


class CreateHintInline(BaseModel):
    content: str
    creator: str

    @field_validator("content", "creator")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text
