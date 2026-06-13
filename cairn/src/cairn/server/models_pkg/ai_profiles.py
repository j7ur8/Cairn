from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from cairn.shared.contracts import (  # noqa: F401  (CANONICAL_AUTH_ENV/HealthCheckItem/auth helpers are re-exports)
    CANONICAL_AUTH_ENV,
    AiProfile,
    AiProfileBase,
    HealthCheckItem,
    HealthCheckResult,
    ProjectAiProfileSnapshot,
    ReasoningType,
    auth_env_warning,
    canonical_auth_env,
)
from cairn.shared.task_types import TASK_TYPE_REGISTRY, builtin_task_type_names  # noqa: F401


class AiWorkerType:
    codex = "codex"
    claudecode = "claudecode"


class AiProfileCreate(AiProfileBase):
    model_config = {"extra": "forbid"}
    # Inherit the same validators as the Base; override the read-only fields
    # so callers can't set them on create.
    seeded_from_worker: str | None = Field(default=None, exclude=True)
    last_health_ok: bool | None = Field(default=None, exclude=True)
    last_health_message: str = Field(default="", exclude=True)
    last_health_at: str | None = Field(default=None, exclude=True)

    @field_validator("worker_type")
    @classmethod
    def validate_worker_type(cls, value: str) -> str:
        if value not in ("codex", "claudecode"):
            raise ValueError("worker_type must be 'codex' or 'claudecode'")
        return value


class AiProfileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    worker_type: Literal["codex", "claudecode"] | None = None
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    available: bool | None = None
    detail: str | None = None
    healthcheck_timeout: float | None = None
    model_reasoning_effort: ReasoningType | None = None
    models: list[str] | None = None
    # Write-only secret. ``None`` = leave unchanged, ``""`` = clear,
    # any other string = replace. Echoed back via ``exclude=True`` so
    # the PUT response never carries the raw value.
    sk: str | None = Field(default=None, exclude=True)

    @field_validator("name", "model")
    @classmethod
    def validate_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("worker_type")
    @classmethod
    def validate_worker_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in ("codex", "claudecode"):
            raise ValueError("worker_type must be 'codex' or 'claudecode'")
        return value

    @field_validator("healthcheck_timeout")
    @classmethod
    def validate_healthcheck_timeout(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value <= 0 or value > 30.0:
            raise ValueError("healthcheck_timeout must be in (0, 30] seconds")
        return float(value)

    @field_validator("models")
    @classmethod
    def validate_models(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = item.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned


class AiProfileSelection(BaseModel):
    primary_profile_id: str | None = None
    primary_model: str | None = None
    primary_reasoning_type: ReasoningType | None = None
    fallback_profile_ids: list[str] = Field(default_factory=list)

    @field_validator("primary_profile_id", "primary_model")
    @classmethod
    def validate_primary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("fallback_profile_ids")
    @classmethod
    def validate_fallback(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = item.strip()
            if not text:
                continue
            if text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned


class TaskAiProfileSelections(BaseModel):
    bootstrap: AiProfileSelection = Field(default_factory=AiProfileSelection)
    explore: AiProfileSelection = Field(default_factory=AiProfileSelection)
    reason: AiProfileSelection = Field(default_factory=AiProfileSelection)


def ai_selections_from_snapshots(
    snapshots: list[ProjectAiProfileSnapshot],
) -> TaskAiProfileSelections:
    by_task = {
        task_type: [snap for snap in snapshots if snap.task_type == task_type]
        for task_type in builtin_task_type_names()
    }
    return TaskAiProfileSelections(
        bootstrap=_selection_from_task_snapshots(by_task["bootstrap"]),
        explore=_selection_from_task_snapshots(by_task["explore"]),
        reason=_selection_from_task_snapshots(by_task["reason"]),
    )


def _selection_from_task_snapshots(
    snapshots: list[ProjectAiProfileSnapshot],
) -> AiProfileSelection:
    primary: str | None = None
    primary_model: str | None = None
    primary_reasoning_type: ReasoningType | None = None
    fallback: list[str] = []
    for snap in snapshots:
        if snap.role == "primary" and primary is None:
            primary = snap.profile_id
            primary_model = snap.snapshot_model
            primary_reasoning_type = snap.snapshot_reasoning_type
        elif snap.role == "fallback":
            fallback.append(snap.profile_id)
    return AiProfileSelection(
        primary_profile_id=primary,
        primary_model=primary_model,
        primary_reasoning_type=primary_reasoning_type,
        fallback_profile_ids=fallback,
    )


class ProjectAiProfilesResponse(BaseModel):
    catalog: list[AiProfile]
    selections: TaskAiProfileSelections = Field(default_factory=TaskAiProfileSelections)
    snapshots: list[ProjectAiProfileSnapshot] = Field(default_factory=list)
    unavailable_profile_ids: list[str] = Field(default_factory=list)


class AiProfileWithHealth(AiProfile):
    """An ``AiProfile`` plus the health check that produced its state."""

    health: HealthCheckResult | None = None


class AiProfileHealthReport(BaseModel):
    """One per-profile health observation reported by the dispatcher."""

    profile_id: str
    ok: bool
    message: str = ""


class AiProfileHealthReportRequest(BaseModel):
    reports: list[AiProfileHealthReport] = Field(default_factory=list)


class AiProfileModelsReport(BaseModel):
    profile_id: str
    models: list[str] = Field(default_factory=list)
    error: str = ""

    @field_validator("profile_id")
    @classmethod
    def validate_profile_id(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("profile_id must not be empty")
        return text

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

    @field_validator("error")
    @classmethod
    def validate_error(cls, value: str) -> str:
        return (value or "").strip()[:1000]


class AiProfileModelsReportRequest(BaseModel):
    reports: list[AiProfileModelsReport] = Field(default_factory=list)


class AiProfileCheckRequest(BaseModel):
    id: str
    profile_id: str
    status: Literal["pending", "running", "completed", "failed"]
    requested_at: str
    started_at: str | None = None
    finished_at: str | None = None
    requested_by: str = ""
    error_message: str = ""


class AiProfileCheckTriggerResponse(BaseModel):
    request_id: str
    status: Literal["pending", "running"]


class AiProfileCheckCompleteRequest(BaseModel):
    ok: bool
    message: str = ""
