from __future__ import annotations

from pydantic import BaseModel, Field


class ObservabilitySettings(BaseModel):
    """observability section — exposed via GET/PUT /observability."""

    model_config = {"extra": "forbid"}

    enabled: bool = True
    record_prompts: bool = True
    record_stdout: bool = True
    record_stderr: bool = True
    record_raw_worker_stream: bool = False
    max_event_bytes: int = Field(default=16384, gt=0)
    max_bytes_per_execution: int = Field(default=10485760, gt=0)
    flush_interval_ms: int = Field(default=250, ge=0)
    flush_max_bytes: int = Field(default=8192, gt=0)
    retention_days: int = Field(default=14, ge=0)
    redaction_patterns: list[str] = Field(default_factory=list)
