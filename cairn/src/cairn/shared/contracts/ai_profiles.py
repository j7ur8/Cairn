from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator

from cairn.shared.contracts.types import ReasoningType
from cairn.shared.task_types import TASK_TYPE_REGISTRY

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
