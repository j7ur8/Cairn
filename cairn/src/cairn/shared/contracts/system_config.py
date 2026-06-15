from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ServerLogRetention(BaseModel):
    """server.log + server.retention — exposed via GET/PUT /server-log-retention."""

    model_config = {"extra": "forbid"}

    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    retention_enabled: bool = True
    retention_interval_seconds: int = Field(default=21600, ge=60)
