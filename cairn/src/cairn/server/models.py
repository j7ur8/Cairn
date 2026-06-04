from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Settings(BaseModel):
    intent_timeout: int = Field(ge=5)
    reason_timeout: int = Field(ge=5)


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


class AttachmentUpload(BaseModel):
    original_filename: str
    stored_filename: str
    size: int
    path: str
    hint_id: str
    hint: str


class AttachmentUploadResponse(BaseModel):
    project_id: str
    attachments: list[AttachmentUpload]


class ProjectFileItem(BaseModel):
    source: Literal["project", "attachment"]
    path: str
    name: str
    size: int
    modified_at: str
    category: Literal["reports", "exploit", "attachments", "other"]


class ProjectFilesResponse(BaseModel):
    project_id: str
    files: list[ProjectFileItem]


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


class CreateHintInline(BaseModel):
    content: str
    creator: str

    @field_validator("content", "creator")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class CapabilitySelection(BaseModel):
    mcp_server_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)

    @field_validator("mcp_server_ids", "skill_ids")
    @classmethod
    def validate_ids(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = item.strip()
            if not text:
                raise ValueError("capability ids must not be empty")
            if text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned


class ProjectRoleSelection(BaseModel):
    role_id: str

    @field_validator("role_id")
    @classmethod
    def validate_role_id(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("role_id must not be empty")
        return text


class CreateProjectRequest(BaseModel):
    title: str
    origin: str
    goal: str
    hints: list[CreateHintInline] | None = None
    capabilities: CapabilitySelection | None = None
    role: ProjectRoleSelection | None = None
    role_id: str | None = None
    proxy_id: str | None = None
    ai_profiles: AiProfileSelection | None = None
    ai_profile_selections: TaskAiProfileSelections | None = None

    @field_validator("title", "origin", "goal", "role_id")
    @classmethod
    def validate_non_empty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class CreateHintRequest(BaseModel):
    content: str
    creator: str

    @field_validator("content", "creator")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class CreateIntentRequest(BaseModel):
    from_: list[str] = Field(alias="from", min_length=1)
    description: str
    creator: str
    worker: str | None = None

    model_config = {"populate_by_name": True}

    @field_validator("description", "creator", "worker")
    @classmethod
    def validate_non_empty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("from_")
    @classmethod
    def validate_fact_ids(cls, value: list[str]) -> list[str]:
        cleaned = []
        for item in value:
            text = item.strip()
            if not text:
                raise ValueError("fact ids must not be empty")
            cleaned.append(text)
        return cleaned


class HeartbeatRequest(BaseModel):
    worker: str
    run_id: str | None = None

    @field_validator("worker", "run_id")
    @classmethod
    def validate_non_empty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class ReasonClaimRequest(BaseModel):
    worker: str
    trigger: str
    run_id: str | None = None
    trigger_hash: str | None = None
    fact_count: int = Field(ge=0)
    hint_count: int = Field(ge=0)
    open_intent_count: int = Field(ge=0)

    @field_validator("worker", "trigger", "run_id", "trigger_hash")
    @classmethod
    def validate_non_empty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class ReasonFinishRequest(BaseModel):
    worker: str
    run_id: str | None = None
    trigger: str
    trigger_hash: str | None = None
    fact_count: int = Field(ge=0)
    hint_count: int = Field(ge=0)
    open_intent_count: int = Field(ge=0)
    outcome: Literal[
        "success",
        "complete",
        "intents",
        "noop",
        "blocked",
        "failed",
        "timeout",
        "rejected",
        "unhealthy",
        "cancelled",
    ]
    error: str | None = None

    @field_validator("worker", "trigger", "run_id", "trigger_hash")
    @classmethod
    def validate_non_empty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("error")
    @classmethod
    def validate_error(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


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


class ConcludeRequest(BaseModel):
    worker: str
    description: str

    @field_validator("worker", "description")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class CompleteRequest(BaseModel):
    from_: list[str] = Field(alias="from", min_length=1)
    description: str
    worker: str

    model_config = {"populate_by_name": True}

    @field_validator("description", "worker")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("from_")
    @classmethod
    def validate_fact_ids(cls, value: list[str]) -> list[str]:
        cleaned = []
        for item in value:
            text = item.strip()
            if not text:
                raise ValueError("fact ids must not be empty")
            cleaned.append(text)
        return cleaned


class ConcludeResponse(BaseModel):
    fact: Fact
    intent: Intent


class UpdateProjectStatusRequest(BaseModel):
    status: Literal["active", "stopped"]


class UpdateProjectTitleRequest(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class ReopenRequest(BaseModel):
    description: str
    creator: str

    @field_validator("description", "creator")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class ReopenResponse(BaseModel):
    project: ProjectMeta
    fact: Fact
    intent: Intent


class ReplayRunCreateRequest(BaseModel):
    title: str
    origin: str
    goal: str
    hints: list[CreateHintInline] | None = None
    capabilities: CapabilitySelection | None = None
    role_id: str | None = None
    ai_profiles: AiProfileSelection | None = None
    ai_profile_selections: TaskAiProfileSelections | None = None

    @field_validator("title", "origin", "goal", "role_id")
    @classmethod
    def validate_non_empty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class ReplayRunCreateResponse(BaseModel):
    run_id: str
    source_project_id: str
    project: ProjectDetail


class ReplayRunAdvanceResponse(BaseModel):
    is_replay: bool
    action: Literal["not_replay", "created_intent", "waiting", "completed", "blocked"]
    status: Literal["not_replay", "active", "completed", "blocked"]
    run_id: str | None = None
    project_id: str | None = None
    intent_id: str | None = None
    detail: str | None = None


class CapabilityCatalogItem(BaseModel):
    id: str
    name: str
    kind: Literal["mcp_server", "skill"]
    description: str = ""
    task_types: list[Literal["bootstrap", "explore", "reason"]]
    available: bool = True
    detail: str = ""


class ProjectCapabilitiesResponse(BaseModel):
    catalog: list[CapabilityCatalogItem]
    selection: CapabilitySelection
    unavailable_mcp_server_ids: list[str] = Field(default_factory=list)
    unavailable_skill_ids: list[str] = Field(default_factory=list)


class RegisterCapabilityCatalogRequest(BaseModel):
    catalog: list[CapabilityCatalogItem]


class RoleCatalogItem(BaseModel):
    id: str
    name: str
    description: str = ""
    task_types: list[Literal["bootstrap", "explore", "reason"]]
    available: bool = True
    prompt_sha256: str = ""
    detail: str = ""


class RegisterRoleCatalogItem(BaseModel):
    id: str
    name: str
    description: str = ""
    task_types: list[Literal["bootstrap", "explore", "reason"]]
    available: bool = True
    prompt: str
    detail: str = ""

    @field_validator("id", "name", "prompt")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class RegisterRoleCatalogRequest(BaseModel):
    roles: list[RegisterRoleCatalogItem]


class ProjectRole(BaseModel):
    project_id: str
    role_id: str
    role_name: str
    role_prompt: str
    role_prompt_sha256: str
    created_at: str


class ProjectRoleResponse(BaseModel):
    role: ProjectRole | None = None



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
    """Full proxy config including credentials. Returned only from GET /proxies/{id}."""
    username: str | None = None
    password: str | None = None


class ProxyCreate(BaseModel):
    name: str
    type: Literal["socks5", "http", "https"]
    host: str
    port: int = Field(gt=0, le=65535)
    username: str | None = None
    password: str | None = None

    @field_validator("name", "host")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("username", "password")
    @classmethod
    def validate_auth(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class ProxyUpdate(BaseModel):
    name: str | None = None
    type: Literal["socks5", "http", "https"] | None = None
    host: str | None = None
    port: int | None = Field(default=None, gt=0, le=65535)
    username: str | None = None
    password: str | None = None

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
    warnings: list[str] = Field(default_factory=list)
    # ``seeded_from_worker`` is set when the row was derived from a
    # ``dispatch.yaml`` worker by the sync endpoint. It is read-only on
    # the wire: callers cannot override it via POST/PUT.
    seeded_from_worker: str | None = None
    last_health_ok: bool | None = None
    last_health_message: str = ""
    last_health_at: str | None = None

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


class AiProfileSelection(BaseModel):
    primary_profile_id: str | None = None
    fallback_profile_ids: list[str] = Field(default_factory=list)

    @field_validator("primary_profile_id")
    @classmethod
    def validate_primary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("primary_profile_id must not be empty")
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
    task_type: Literal["bootstrap", "explore", "reason", "legacy"] = "legacy"
    role: Literal["primary", "fallback"]
    position: int
    snapshot_name: str
    snapshot_worker_type: Literal["codex", "claudecode"]
    snapshot_provider: str = ""
    snapshot_base_url: str = ""
    snapshot_model: str
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


class AiProfileHealthReport(BaseModel):
    """One per-profile health observation reported by the dispatcher."""

    profile_id: str
    ok: bool
    message: str = ""


class AiProfileHealthReportRequest(BaseModel):
    reports: list[AiProfileHealthReport] = Field(default_factory=list)


CreateProjectRequest.model_rebuild()
ReplayRunCreateRequest.model_rebuild()
AiProfileSyncRequest.model_rebuild()
