from __future__ import annotations

from typing import Literal
from typing import Literal as _Literal  # noqa: F401

from pydantic import BaseModel, Field, computed_field, field_validator

ProcessState = Literal["running", "completed", "failed", "timeout", "cancelled", "stale"]
TaskType = str  # any name registered in TASK_TYPE_REGISTRY
EventKind = Literal[
    "prompt",
    "stdout",
    "stderr",
    "model_response",
    "parse_error",
    "timeout",
    "cancelled",
    "process_end",
    "result",
    "error",
    "agent_message",
    "thinking",
    "tool_call",
    "tool_result",
    "command_start",
    "command_end",
    "usage",
    "session_init",
    "api_retry",
    "system_event",
    "capability_manifest",
    "trace_parse_error",
]
EventStream = Literal["system", "prompt", "stdout", "stderr", "result", "error"]


_RECORD_STREAMS = ("prompts", "stdout", "stderr")


class ObservabilitySettings(BaseModel):
    enabled: bool = True
    # New authoritative field. Old ``record_*`` booleans are kept as
    # computed properties so wire format and reporter.py keep working.
    record: set[str] = Field(default_factory=lambda: {"prompts", "stdout", "stderr"})

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
    max_event_bytes: int = Field(default=16384, gt=0)
    max_bytes_per_execution: int = Field(default=10485760, gt=0)
    flush_interval_ms: int = Field(default=250, ge=0)
    flush_max_bytes: int = Field(default=8192, gt=0)
    retention_days: int = Field(default=14, ge=0)
    redaction_patterns: list[str] = Field(default_factory=list)


class LlmExecution(BaseModel):
    id: str
    project_id: str
    intent_id: str | None = None
    task_type: TaskType
    worker: str
    process_state: ProcessState
    started_at: str
    ended_at: str | None = None
    last_event_at: str | None = None
    event_count: int
    bytes_written: int
    returncode: int | None = None
    timed_out: int = 0
    error_kind: str | None = None
    produced_fact_id: str | None = None
    created_intent_ids: str | None = None


class LlmExecutionEvent(BaseModel):
    sequence: int
    execution_id: str
    project_id: str
    intent_id: str | None = None
    task_type: TaskType
    worker: str
    phase: str
    event_kind: EventKind
    stream: EventStream
    content: str
    truncated: int = 0
    redacted: int = 0
    created_at: str


class CreateExecutionRequest(BaseModel):
    id: str
    intent_id: str | None = None
    task_type: TaskType
    worker: str

    @field_validator("id", "worker")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class CreateExecutionResponse(BaseModel):
    execution: LlmExecution


class CreateEventRequest(BaseModel):
    phase: str
    event_kind: EventKind
    stream: EventStream
    content: str

    @field_validator("phase")
    @classmethod
    def validate_phase(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class CreateEventResponse(BaseModel):
    event: LlmExecutionEvent | None
    dropped: bool = False


class CreateEventsBatchRequest(BaseModel):
    events: list[CreateEventRequest] = Field(min_length=1, max_length=200)


class CreateEventsBatchResponse(BaseModel):
    events: list[LlmExecutionEvent | None]
    dropped: int = 0


class FinishExecutionRequest(BaseModel):
    process_state: ProcessState
    returncode: int | None = None
    timed_out: bool = False
    error_kind: str | None = None
    produced_fact_id: str | None = None
    created_intent_ids: list[str] | None = None


class ExecutionListResponse(BaseModel):
    executions: list[LlmExecution]


class EventListResponse(BaseModel):
    events: list[LlmExecutionEvent]


class IncrementalEventListResponse(BaseModel):
    events: list[LlmExecutionEvent]
    last_sequence: int = 0


class LlmUsageActivity(BaseModel):
    latest_usage_sequence: int | None = None
    latest_usage_at: str | None = None
    subtype: str | None = None
    tokens: int | None = None
    delta: int | None = None
    hidden_usage_count: int = 0


class LlmEventStats(BaseModel):
    total: int
    returned: int
    by_kind: dict[str, int] = Field(default_factory=dict)
    hidden_by_kind: dict[str, int] = Field(default_factory=dict)


class EventViewResponse(BaseModel):
    primary_events: list[LlmExecutionEvent]
    activity: LlmUsageActivity | None = None
    stats: LlmEventStats
    last_sequence: int
