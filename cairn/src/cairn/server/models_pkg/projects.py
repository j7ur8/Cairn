from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator


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
