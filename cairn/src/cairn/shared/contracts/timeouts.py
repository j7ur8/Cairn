from __future__ import annotations

from pydantic import BaseModel, Field


class BootstrapTaskTimeouts(BaseModel):
    model_config = {"extra": "forbid"}

    timeout: int = Field(gt=0)
    conclude_timeout: int = Field(gt=0)


class ExploreTaskTimeouts(BaseModel):
    model_config = {"extra": "forbid"}

    timeout: int = Field(gt=0)
    conclude_timeout: int = Field(gt=0)


class ReasonTaskTimeouts(BaseModel):
    model_config = {"extra": "forbid"}

    timeout: int = Field(gt=0)
    max_intents: int = Field(default=3, gt=0)


class TaskTimeouts(BaseModel):
    model_config = {"extra": "forbid"}

    bootstrap: BootstrapTaskTimeouts
    explore: ExploreTaskTimeouts
    reason: ReasonTaskTimeouts
