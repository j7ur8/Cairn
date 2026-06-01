from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ProcessState = Literal["running", "completed", "failed", "timeout", "cancelled", "stale"]
TaskType = Literal["bootstrap", "explore", "reason"]
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
    "trace_parse_error",
]
EventStream = Literal["system", "prompt", "stdout", "stderr", "result", "error"]


class ObservabilitySettings(BaseModel):
    enabled: bool = True
    record_prompts: bool = True
    record_stdout: bool = True
    record_stderr: bool = True
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
