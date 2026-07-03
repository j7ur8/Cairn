from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from cairn.shared.contracts import Fact, Intent, IntentPhaseCheckpoint


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


class IntentPhaseCheckpointUpsertRequest(BaseModel):
    worker_name: str
    worker_type: str
    session_id: str

    @field_validator("worker_name", "worker_type", "session_id")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class IntentPhaseCheckpointFailedRequest(BaseModel):
    last_error: str

    @field_validator("last_error")
    @classmethod
    def validate_last_error(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class IntentPhaseCheckpointResponse(BaseModel):
    checkpoint: IntentPhaseCheckpoint | None = None
