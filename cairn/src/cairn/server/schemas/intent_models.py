from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from cairn.shared.contracts import Fact, Intent


class CreateIntentRequest(BaseModel):
    from_: list[str] = Field(alias="from", min_length=1)
    description: str
    creator: str
    worker: str | None = None
    priority_score: float | None = None
    intent_kind: str | None = None
    tags: list[str] = Field(default_factory=list)
    score_reason: str | None = None
    branch_key: str | None = None
    branch_depth: int = 0
    expected_value: float | None = None

    model_config = {"populate_by_name": True}

    @field_validator("description", "creator", "worker", "intent_kind", "score_reason", "branch_key")
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

    @field_validator("priority_score")
    @classmethod
    def validate_priority_score(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value < 0.0 or value > 1.0:
            raise ValueError("priority_score must be between 0.0 and 1.0")
        return value

    @field_validator("branch_depth")
    @classmethod
    def validate_branch_depth(cls, value: int) -> int:
        if value < 0:
            raise ValueError("branch_depth must be greater than or equal to 0")
        return value

    @field_validator("expected_value")
    @classmethod
    def validate_expected_value(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value < 0.0 or value > 1.0:
            raise ValueError("expected_value must be between 0.0 and 1.0")
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            text = item.strip()
            if not text:
                raise ValueError("tags must not contain empty values")
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


class ConcludeResponse(BaseModel):
    fact: Fact
    intent: Intent
