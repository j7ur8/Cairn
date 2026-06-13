from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

# Re-export shim: the graph models and LLM-event-kind helpers live in
# cairn.shared.contracts. Many server modules (routers, mappers,
# application, sibling model modules) import them from here, so these
# names are intentionally surfaced (noqa: F401) even though this module
# only defines the attachment/file/hint request models below.
from cairn.shared.contracts import (  # noqa: F401
    DEFAULT_LLM_HIDDEN_EVENT_KINDS,
    LLM_EVENT_KIND_OPTIONS,
    Fact,
    Hint,
    Intent,
    ProjectDetail,
    ProjectMeta,
    ProjectReason,
    ProjectSummary,
    ProjectWorkSummary,
    hidden_kinds_from_visible,
    normalize_llm_event_kinds,
    parse_llm_hidden_event_kinds,
    visible_kinds_from_hidden,
)


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
