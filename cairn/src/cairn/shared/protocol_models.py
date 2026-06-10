from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator

from cairn.shared.task_types import TASK_TYPE_REGISTRY


ReasoningType = Literal["low", "medium", "high", "xhigh"]


class Settings(BaseModel):
    intent_timeout: int = Field(ge=5)
    reason_timeout: int = Field(ge=5)


class ProxySummary(BaseModel):
    id: str
    name: str
    type: Literal["socks5", "http", "https"]
    host: str
    port: int
    has_auth: bool = False
    created_at: str
    updated_at: str


class ProxyConfig(ProxySummary):
    username: str | None = None
    password: str | None = None


CANONICAL_AUTH_ENV: dict[str, str] = {
    "codex": "OPENAI_API_KEY",
    "claudecode": "ANTHROPIC_AUTH_TOKEN",
}


def canonical_auth_env(worker_type: str) -> str:
    return CANONICAL_AUTH_ENV.get(worker_type, "")


def auth_env_warning(worker_type: str, api_key_env: str) -> str | None:
    canonical = canonical_auth_env(worker_type)
    if canonical is None or not api_key_env:
        return None
    if api_key_env.strip() == canonical:
        return None
    return (
        f"auth env var '{api_key_env}' differs from the canonical "
        f"'{canonical}' for worker_type '{worker_type}'. AI Profile "
        f"stores the worker runtime env name, so the dispatcher host "
        f"must also provide '{canonical}' directly."
    )


class HealthCheckItem(BaseModel):
    name: str
    ok: bool
    message: str = ""


class HealthCheckResult(BaseModel):
    ok: bool
    checks: list[HealthCheckItem] = Field(default_factory=list)


class AiProfileBase(BaseModel):
    name: str
    description: str = ""
    worker_type: Literal["codex", "claudecode"]
    provider: str = ""
    base_url: str = ""
    model: str
    api_key_env: str = ""
    available: bool = True
    detail: str = ""
    healthcheck_timeout: float = 1.0
    model_reasoning_effort: ReasoningType | None = None
    warnings: list[str] = Field(default_factory=list)
    seeded_from_worker: str | None = None
    last_health_ok: bool | None = None
    last_health_message: str = ""
    last_health_at: str | None = None
    models: list[str] = Field(default_factory=list)
    sk: str = Field(default="", exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sk_set(self) -> bool:
        return bool(self.sk.strip())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sk_preview(self) -> str:
        raw = self.sk.strip()
        if not raw:
            return ""
        if len(raw) <= 4:
            return "***"
        return f"***{raw[-4:]}"

    @field_validator("name", "model")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("provider", "base_url", "description", "detail")
    @classmethod
    def validate_optional_text(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("healthcheck_timeout")
    @classmethod
    def validate_healthcheck_timeout(cls, value: float) -> float:
        if value <= 0 or value > 30.0:
            raise ValueError("healthcheck_timeout must be in (0, 30] seconds")
        return float(value)

    @field_validator("models")
    @classmethod
    def validate_models(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = item.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned


class AiProfile(AiProfileBase):
    id: str
    created_at: str
    updated_at: str


class ProjectAiProfileSnapshot(BaseModel):
    profile_id: str
    task_type: str

    @field_validator("task_type")
    @classmethod
    def validate_task_type(cls, value: str) -> str:
        if not TASK_TYPE_REGISTRY.is_valid(value):
            raise ValueError(
                f"unknown task_type: {value!r}; "
                f"known: {', '.join(TASK_TYPE_REGISTRY.names())}"
            )
        return value

    role: Literal["primary", "fallback"]
    position: int
    snapshot_name: str
    snapshot_worker_type: Literal["codex", "claudecode"]
    snapshot_provider: str = ""
    snapshot_base_url: str = ""
    snapshot_model: str
    snapshot_reasoning_type: ReasoningType | None = None
    snapshot_api_key_env: str


LLM_EVENT_KIND_OPTIONS: tuple[str, ...] = (
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
)
DEFAULT_LLM_HIDDEN_EVENT_KINDS: tuple[str, ...] = ("usage",)


def normalize_llm_event_kinds(value: list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return list(LLM_EVENT_KIND_OPTIONS)
    allowed = set(LLM_EVENT_KIND_OPTIONS)
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text:
            raise ValueError("event kind must not be empty")
        if text not in allowed:
            raise ValueError(f"unknown event kind: {text}")
        if text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def hidden_kinds_from_visible(value: list[str] | tuple[str, ...] | None) -> list[str]:
    visible = set(normalize_llm_event_kinds(value))
    return [kind for kind in LLM_EVENT_KIND_OPTIONS if kind not in visible]


def visible_kinds_from_hidden(value: list[str] | tuple[str, ...] | None) -> list[str]:
    hidden = set(normalize_llm_event_kinds(value))
    return [kind for kind in LLM_EVENT_KIND_OPTIONS if kind not in hidden]


def parse_llm_hidden_event_kinds(value: str | None) -> list[str]:
    if not value:
        return list(DEFAULT_LLM_HIDDEN_EVENT_KINDS)
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return list(DEFAULT_LLM_HIDDEN_EVENT_KINDS)
    if not isinstance(raw, list):
        return list(DEFAULT_LLM_HIDDEN_EVENT_KINDS)
    try:
        return normalize_llm_event_kinds(raw)
    except ValueError:
        return list(DEFAULT_LLM_HIDDEN_EVENT_KINDS)


class Fact(BaseModel):
    id: str
    description: str


class Intent(BaseModel):
    id: str
    from_: list[str] = Field(alias="from")
    to: str | None = None
    description: str
    creator: str
    worker: str | None = None
    last_heartbeat_at: str | None = None
    created_at: str
    concluded_at: str | None = None

    model_config = {"populate_by_name": True}


class Hint(BaseModel):
    id: str
    content: str
    creator: str
    created_at: str


class ProjectReason(BaseModel):
    worker: str
    run_id: str | None = None
    trigger: str
    started_at: str
    last_heartbeat_at: str


class ProjectMeta(BaseModel):
    id: str
    title: str
    status: Literal["active", "stopped", "completed"]
    created_at: str
    reason: ProjectReason | None = None
    llm_hidden_event_kinds: list[str] = Field(default_factory=lambda: list(DEFAULT_LLM_HIDDEN_EVENT_KINDS))

    @field_validator("llm_hidden_event_kinds")
    @classmethod
    def validate_llm_hidden_event_kinds(cls, value: list[str]) -> list[str]:
        return normalize_llm_event_kinds(value)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def llm_visible_event_kinds(self) -> list[str]:
        return visible_kinds_from_hidden(self.llm_hidden_event_kinds)


class ProjectSummary(ProjectMeta):
    fact_count: int
    intent_count: int
    working_intent_count: int
    unclaimed_intent_count: int
    hint_count: int


class ProjectDetail(BaseModel):
    project: ProjectMeta
    facts: list[Fact]
    intents: list[Intent]
    hints: list[Hint]
    proxy: ProxySummary | None = None


class ReasonState(BaseModel):
    project_id: str
    trigger: str
    trigger_hash: str
    fact_count: int
    hint_count: int
    open_intent_count: int
    outcome: str
    failure_count: int
    last_error: str
    next_retry_at: str | None = None
    updated_at: str
