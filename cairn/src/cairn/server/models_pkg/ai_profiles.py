from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator

from cairn.server.task_types import TASK_TYPE_REGISTRY

class AiWorkerType:
    codex = "codex"
    claudecode = "claudecode"


class HealthCheckItem(BaseModel):
    name: str
    ok: bool
    message: str = ""


class HealthCheckResult(BaseModel):
    ok: bool
    checks: list[HealthCheckItem] = Field(default_factory=list)


# Canonical auth-var name per worker type. Kept in sync with
# ``cairn.dispatcher.config.WORKER_ENV_KEYS``; the server only needs the
# *names* to surface warnings, not the worker-side config object.
CANONICAL_AUTH_ENV: dict[str, str] = {
    "codex": "OPENAI_API_KEY",
    "claudecode": "ANTHROPIC_AUTH_TOKEN",
}


def auth_env_warning(worker_type: str, api_key_env: str) -> str | None:
    canonical = CANONICAL_AUTH_ENV.get(worker_type)
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


class AiProfileBase(BaseModel):
    name: str
    description: str = ""
    worker_type: Literal["codex", "claudecode"]
    provider: str = ""
    base_url: str = ""
    model: str
    api_key_env: str
    available: bool = True
    detail: str = ""
    healthcheck_timeout: float = 1.0
    model_reasoning_effort: ReasoningType | None = None
    warnings: list[str] = Field(default_factory=list)
    # ``seeded_from_worker`` is set when the row was derived from a
    # ``dispatch.yaml`` worker by the sync endpoint. It is read-only on
    # the wire: callers cannot override it via POST/PUT.
    seeded_from_worker: str | None = None
    last_health_ok: bool | None = None
    last_health_message: str = ""
    last_health_at: str | None = None
    models: list[str] = Field(default_factory=list)
    # Raw secret. Excluded from JSON responses; the read shape exposes
    # only ``sk_set`` / ``sk_preview`` so the form can show whether a
    # key is on file without revealing it. The dispatcher secret
    # endpoint reads this column directly from SQLite, never via the
    # serialized model. ``sk`` stays on the input shape so the Add /
    # Edit form can populate it.
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

    @field_validator("name", "model", "api_key_env")
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

    @field_validator("name", "model", "api_key_env")
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


class ProjectAiProfileSnapshot(BaseModel):
    profile_id: str
    task_type: str = "legacy"  # validated by TaskTypeRegistry below

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


class ProjectAiProfilesResponse(BaseModel):
    catalog: list[AiProfile]
    selection: AiProfileSelection
    selections: TaskAiProfileSelections = Field(default_factory=TaskAiProfileSelections)
    snapshots: list[ProjectAiProfileSnapshot] = Field(default_factory=list)
    unavailable_profile_ids: list[str] = Field(default_factory=list)


class AiProfileWithHealth(AiProfile):
    """An ``AiProfile`` plus the health check that produced its state."""

    health: HealthCheckResult | None = None


class AiProfileSyncRequest(BaseModel):
    """Body for ``POST /ai-profiles/sync``.

    The dispatcher sends its ``workers[*].env`` already translated: model
    and base_url come from the canonical env var names, ``api_key_env``
    is the *name* of the auth env var (not its value).
    """

    workers: list["AiProfileSyncWorker"]


class AiProfileSyncWorker(BaseModel):
    name: str
    # ``worker_type`` is intentionally ``str`` here: the router filters
    # down to the supported set (``codex`` / ``claudecode``) and drops
    # anything else with a debug log. This keeps the wire format loose
    # so a future ``pi`` / ``mock`` rollout does not require a schema
    # change in lock-step with the dispatcher.
    worker_type: str
    model: str
    base_url: str = ""
    api_key_env: str
    provider: str = ""
    models: list[str] = Field(default_factory=list)
    model_reasoning_effort: ReasoningType | None = None
    # Resolved secret the dispatcher already pulled out of its host
    # env at sync time. Optional: a missing value means "leave whatever
    # the operator already has in the DB", so re-syncs never wipe a
    # value the operator typed into the Add/Edit form.
    sk: str | None = Field(default=None, exclude=True)

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
