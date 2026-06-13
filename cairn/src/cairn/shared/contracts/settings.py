from __future__ import annotations

from pydantic import BaseModel, Field


class Settings(BaseModel):
    intent_timeout: int = Field(ge=5)
    reason_timeout: int = Field(ge=5)
