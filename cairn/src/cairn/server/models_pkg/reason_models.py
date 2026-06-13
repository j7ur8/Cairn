from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Re-export shim: ReasonState lives in cairn.shared.contracts; package
# __init__ and other modules import it from here. Unused locally by design.
from cairn.shared.contracts import ReasonState  # noqa: F401


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
