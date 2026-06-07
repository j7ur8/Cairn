from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator

ReasoningType = Literal["low", "medium", "high", "xhigh"]




class Settings(BaseModel):
    intent_timeout: int = Field(ge=5)
    reason_timeout: int = Field(ge=5)
