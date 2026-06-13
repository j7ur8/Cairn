from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, computed_field


class ReasonTaskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout: int = Field(gt=0)
    max_intents: int = Field(gt=0, default=3)


class ExploreTaskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout: int = Field(gt=0)
    conclude_timeout: int = Field(gt=0)


class BootstrapTaskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout: int = Field(gt=0)
    conclude_timeout: int = Field(gt=0)


class TasksConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bootstrap: BootstrapTaskConfig
    reason: ReasonTaskConfig
    explore: ExploreTaskConfig


class ObservabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    record: set[str] = Field(default_factory=lambda: {"prompts", "stdout", "stderr"})
    record_raw_worker_stream: bool = False
    max_event_bytes: int = Field(default=16384, gt=0)
    max_bytes_per_execution: int = Field(default=10485760, gt=0)
    flush_interval_ms: int = Field(default=250, ge=0)
    flush_max_bytes: int = Field(default=8192, gt=0)
    retention_days: int = Field(default=14, ge=0)
    redaction_patterns: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def record_prompts(self) -> bool:
        return "prompts" in self.record

    @computed_field  # type: ignore[prop-decorator]
    @property
    def record_stdout(self) -> bool:
        return "stdout" in self.record

    @computed_field  # type: ignore[prop-decorator]
    @property
    def record_stderr(self) -> bool:
        return "stderr" in self.record
