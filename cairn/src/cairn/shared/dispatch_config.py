from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import re
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from cairn.shared.task_types import TASK_TYPE_REGISTRY, builtin_task_type_names, is_known_task_type


def _check_known_task_types(value: list[str]) -> list[str]:
    """Reject any ``task_type`` not present in :data:`TASK_TYPE_REGISTRY`.

    Used by the per-model ``validate_task_types`` field validators so
    the canonical set of valid task types lives in one place.
    """
    unknown = [item for item in value if not is_known_task_type(item)]
    if unknown:
        raise ValueError(
            f"unknown task_types: {unknown!r}; "
            f"known: {', '.join(TASK_TYPE_REGISTRY.names())}"
        )
    return value


TaskType = str  # any name registered in TASK_TYPE_REGISTRY
WorkerType = Literal["claudecode", "codex", "pi", "mock"]
ContainerInactiveAction = Literal["remove", "stop"]
ReasoningEffort = Literal["low", "medium", "high", "xhigh"]

WORKER_ENV_KEYS: dict[WorkerType, tuple[str, ...]] = {
    "claudecode": (
        "ANTHROPIC_MODEL",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
    ),
    "codex": (
        "CODEX_MODEL",
        "CODEX_BASE_URL",
        "OPENAI_API_KEY",
    ),
    "pi": (
        "PI_MODEL",
        "PI_BASE_URL",
        "PI_API_KEY",
        "PI_PROVIDER_API",
    ),
    "mock": (),
}

DEFAULT_PROMPT_REQUIRED_TOKENS: dict[str, tuple[str, ...]] = {
    "reason.md": ("{graph_yaml}", "{fact_ids}", "{open_intents}", "{max_intents}", "{capability_instructions}", "{role_instructions}"),
    "explore.md": ("{graph_yaml}", "{intent_id}", "{intent_description}", "{capability_instructions}", "{role_instructions}"),
    "explore_conclude.md": ("{graph_yaml}", "{intent_id}", "{intent_description}"),
    "bootstrap.md": ("{origin}", "{goal}", "{hints}", "{capability_instructions}", "{role_instructions}"),
    "bootstrap_conclude.md": ("{origin}", "{goal}", "{hints}"),
}

PROMPT_REQUIRED_TOKENS_BY_GROUP: dict[str, dict[str, tuple[str, ...]]] = {
    "mock": {
        "reason.md": ("{fact_ids}", "{open_intents}", "{max_intents}"),
        "explore.md": ("{intent_id}",),
        "explore_conclude.md": ("{intent_id}",),
        "bootstrap.md": ("{origin}", "{goal}", "{hints}"),
        "bootstrap_conclude.md": ("{origin}", "{goal}", "{hints}"),
    }
}

MOCK_ALLOWED_OUTCOMES: dict[str, frozenset[str]] = {
    "healthcheck": frozenset({"ok", "fail"}),
    "reason": frozenset({"complete", "intent", "noop", "rejected", "invalid_json", "invalid_payload", "command_fail"}),
    "explore_execute": frozenset({"fact", "rejected", "invalid_json", "invalid_payload", "command_fail"}),
    "explore_conclude": frozenset({"fact", "rejected", "invalid_json", "invalid_payload", "command_fail"}),
    "bootstrap": frozenset({"complete", "fact", "rejected", "invalid_json", "invalid_payload", "command_fail"}),
    "bootstrap_conclude": frozenset({"fact", "rejected", "invalid_json", "invalid_payload", "command_fail"}),
}

MOCK_DEFAULT_BEHAVIOR: dict[str, dict[str, Any]] = {
    "healthcheck": {
        "delay": [0.05, 0.15],
        "outcomes": {"ok": "1.0", "fail": "0.0"},
    },
    "reason": {
        "delay": [0.05, 0.3],
        "outcomes": {
            "complete": "0.0",
            "intent": "1.0",
            "noop": "0.0",
            "rejected": "0.0",
            "invalid_json": "0.0",
            "invalid_payload": "0.0",
            "command_fail": "0.0",
        },
    },
    "explore_execute": {
        "delay": [0.05, 0.3],
        "outcomes": {
            "fact": "1.0",
            "rejected": "0.0",
            "invalid_json": "0.0",
            "invalid_payload": "0.0",
            "command_fail": "0.0",
        },
    },
    "explore_conclude": {
        "delay": [0.05, 0.3],
        "outcomes": {
            "fact": "1.0",
            "rejected": "0.0",
            "invalid_json": "0.0",
            "invalid_payload": "0.0",
            "command_fail": "0.0",
        },
    },
    "bootstrap": {
        "delay": [0.05, 0.3],
        "outcomes": {
            "complete": "1.0",
            "fact": "0.0",
            "rejected": "0.0",
            "invalid_json": "0.0",
            "invalid_payload": "0.0",
            "command_fail": "0.0",
        },
    },
    "bootstrap_conclude": {
        "delay": [0.05, 0.3],
        "outcomes": {
            "fact": "1.0",
            "rejected": "0.0",
            "invalid_json": "0.0",
            "invalid_payload": "0.0",
            "command_fail": "0.0",
        },
    },
}

MOCK_ALLOWED_ENV_KEYS = frozenset(
    {f"MOCK_{phase.upper()}" for phase in MOCK_ALLOWED_OUTCOMES}
)


class ReasonTaskConfig(BaseModel):
    timeout: int = Field(gt=0)
    max_intents: int = Field(gt=0, default=3)


class ExploreTaskConfig(BaseModel):
    timeout: int = Field(gt=0)
    conclude_timeout: int = Field(gt=0)


class BootstrapTaskConfig(BaseModel):
    timeout: int = Field(gt=0)
    conclude_timeout: int = Field(gt=0)


class TasksConfig(BaseModel):
    bootstrap: BootstrapTaskConfig
    reason: ReasonTaskConfig
    explore: ExploreTaskConfig


class ObservabilityConfig(BaseModel):
    enabled: bool = True
    # New authoritative field. Old ``record_*`` booleans are kept as
    # computed properties so wire format and reporter.py keep working.
    record: set[str] = Field(default_factory=lambda: {"prompts", "stdout", "stderr"})
    record_raw_worker_stream: bool = False
    max_event_bytes: int = Field(default=16384, gt=0)

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
    max_bytes_per_execution: int = Field(default=10485760, gt=0)
    flush_interval_ms: int = Field(default=250, ge=0)
    flush_max_bytes: int = Field(default=8192, gt=0)
    retention_days: int = Field(default=14, ge=0)
    redaction_patterns: list[str] = Field(default_factory=list)


class BindMountConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    host_path: str
    container_path: str
    read_only: bool = False

    @field_validator("name", "host_path", "container_path")
    @classmethod
    def validate_non_empty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("container_path")
    @classmethod
    def validate_container_path(cls, value: str) -> str:
        path = value.strip()
        if not path.startswith("/"):
            raise ValueError("container_path must be absolute")
        parts = Path(path).parts
        if any(part in ("", ".", "..") for part in parts[1:]):
            raise ValueError("container_path must not contain empty, '.', or '..' segments")
        return path

    @field_validator("host_path")
    @classmethod
    def validate_host_path(cls, value: str) -> str:
        path = value.strip()
        if not path:
            raise ValueError("host_path must not be empty")
        if "\x00" in path:
            raise ValueError("host_path must not contain NUL bytes")
        return path


class RemoteDnslogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = ""

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return value.strip()


class RemoteSshConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = ""
    port: int = Field(default=22, gt=0, le=65535)
    username: str = ""
    password: str = ""

    @field_validator("host", "username", "password")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return value.strip()

    @property
    def is_complete(self) -> bool:
        return bool(self.host and self.username and self.password)


class RemoteSupportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    dnslog: RemoteDnslogConfig = Field(default_factory=RemoteDnslogConfig)
    ssh: RemoteSshConfig = Field(default_factory=RemoteSshConfig)

    @property
    def dnslog_configured(self) -> bool:
        return self.enabled and bool(self.dnslog.url)

    @property
    def ssh_configured(self) -> bool:
        return self.enabled and self.ssh.is_complete

    @property
    def has_available_resource(self) -> bool:
        return self.dnslog_configured or self.ssh_configured

    def environment(self) -> dict[str, str]:
        if not self.enabled:
            return {}
        env: dict[str, str] = {}
        if self.dnslog.url:
            env["CAIRN_DNSLOG_URL"] = self.dnslog.url
        if self.ssh.is_complete:
            env.update(
                {
                    "CAIRN_REMOTE_SSH_HOST": self.ssh.host,
                    "CAIRN_REMOTE_SSH_PORT": str(self.ssh.port),
                    "CAIRN_REMOTE_SSH_USERNAME": self.ssh.username,
                    "CAIRN_REMOTE_SSH_PASSWORD": self.ssh.password,
                }
            )
        if env:
            env["CAIRN_REMOTE_SUPPORT_ENABLED"] = "true"
        return env


class McpServerCapabilityConfig(BaseModel):
    """Capability config for a single MCP server.

    Two transports are supported:

    - ``stdio``: the MCP server runs as a local subprocess
      inside the worker container, addressed by ``command`` / ``args`` / ``env``.
    - ``http``: the agent connects to a remote MCP server over HTTP. The server
      is typically reached via ``host.docker.internal`` (macOS/Windows Docker
      Desktop) or a user-defined alias (Linux Docker Engine: ``--add-host``).
      Auth is configured directly in ``headers``.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    transport: Literal["stdio", "http"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    healthcheck_timeout: float = Field(default=1.0, gt=0, le=30)
    source_path: str | None = None
    probe_config: dict[str, Any] = Field(default_factory=dict)
    task_types: list[TaskType] = Field(default_factory=lambda: ["bootstrap", "explore"])
    description: str = ""
    detail: str = ""
    available: bool = True
    last_probe_status: str | None = None
    last_probe_at: str | None = None
    last_probe_message: str = ""
    # Skills that the dispatcher must auto-inject whenever a project
    # task selects this MCP. Mirrors skill.requires_ids in the opposite
    # direction: an MCP declares which skills it needs. Each id must be
    # declared in the same ``capabilities.skills`` block; the
    # ``CapabilitiesConfig`` validator below enforces that at startup
    # so a broken YAML never reaches runtime.
    required_skill_ids: list[str] = Field(default_factory=list)
    use_when: list[str] = Field(default_factory=list)
    activation_hint: str = ""

    @field_validator("id", "name", "command", "source_path", "url")
    @classmethod
    def validate_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return value

    @model_validator(mode="after")
    def validate_transport(self) -> "McpServerCapabilityConfig":
        if self.transport == "stdio":
            if not self.command:
                raise ValueError(
                    f"mcp_server {self.id}: stdio transport requires 'command'"
                )
        elif self.transport == "http":
            if not self.url:
                raise ValueError(
                    f"mcp_server {self.id}: http transport requires 'url'"
                )
        else:
            raise ValueError(
                f"mcp_server {self.id}: transport must be 'stdio' or 'http', got {self.transport!r}"
            )
        return self

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("id must not be empty")
        if any(ch.isspace() for ch in text) or "/" in text or "\\" in text:
            raise ValueError("id must not contain whitespace, '/', or '\\'")
        return text

    @field_validator("task_types")
    @classmethod
    def validate_task_types(cls, value: list[TaskType]) -> list[TaskType]:
        if not value:
            raise ValueError("task_types must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("task_types must be unique")
        _check_known_task_types(value)
        return value

    @field_validator("required_skill_ids", "use_when")
    @classmethod
    def validate_string_list(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in value or []:
            key = (item or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped

    @field_validator("activation_hint")
    @classmethod
    def validate_activation_hint(cls, value: str) -> str:
        return value.strip()


class SkillCapabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    source_path: str
    task_types: list[TaskType] = Field(default_factory=lambda: list(builtin_task_type_names()))
    description: str = ""
    use_when: list[str] = Field(default_factory=list)
    preferred_mcp_ids: list[str] = Field(default_factory=list)
    activation_hint: str = ""
    detail: str = ""
    available: bool = True
    requires_ids: list[str] = Field(default_factory=list)
    probe_config: dict[str, Any] = Field(default_factory=dict)
    last_probe_status: str | None = None
    last_probe_at: str | None = None
    last_probe_message: str = ""

    @field_validator("id", "name", "source_path")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("id must not be empty")
        if any(ch.isspace() for ch in text) or "/" in text or "\\" in text:
            raise ValueError("id must not contain whitespace, '/', or '\\'")
        return text

    @field_validator("task_types")
    @classmethod
    def validate_task_types(cls, value: list[TaskType]) -> list[TaskType]:
        if not value:
            raise ValueError("task_types must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("task_types must be unique")
        _check_known_task_types(value)
        return value

    @field_validator("use_when", "preferred_mcp_ids", "requires_ids")
    @classmethod
    def validate_string_list(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in value or []:
            key = (item or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped

    @field_validator("activation_hint")
    @classmethod
    def validate_activation_hint(cls, value: str) -> str:
        return value.strip()


class CapabilitiesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mcp_servers: list[McpServerCapabilityConfig] = Field(default_factory=list)
    skills: list[SkillCapabilityConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "CapabilitiesConfig":
        mcp_ids = [item.id for item in self.mcp_servers]
        skill_ids = [item.id for item in self.skills]
        if len(mcp_ids) != len(set(mcp_ids)):
            raise ValueError("capabilities.mcp_servers ids must be unique")
        if len(skill_ids) != len(set(skill_ids)):
            raise ValueError("capabilities.skills ids must be unique")
        # Every MCP's required_skill_ids must point at a declared skill.
        # Caught here so a broken dispatch.yaml fails fast at startup
        # instead of surprising the expansion layer mid-dispatch.
        declared_skill_ids = set(skill_ids)
        for mcp in self.mcp_servers:
            for required_skill_id in mcp.required_skill_ids:
                if required_skill_id not in declared_skill_ids:
                    raise ValueError(
                        f"mcp_server {mcp.id} requires skill {required_skill_id!r} "
                        f"but that id is not declared in capabilities.skills"
                    )
        for skill in self.skills:
            for required_skill_id in skill.requires_ids:
                if required_skill_id not in declared_skill_ids:
                    raise ValueError(
                        f"skill {skill.id} requires skill {required_skill_id!r} "
                        f"but that id is not declared in capabilities.skills"
                    )
        declared_mcp_ids = set(mcp_ids)
        for skill in self.skills:
            for preferred_mcp_id in skill.preferred_mcp_ids:
                if preferred_mcp_id not in declared_mcp_ids:
                    raise ValueError(
                        f"skill {skill.id} prefers mcp_server {preferred_mcp_id!r} "
                        f"but that id is not declared in capabilities.mcp_servers"
                    )
        return self


class RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    task_types: list[TaskType] = Field(default_factory=lambda: list(builtin_task_type_names()))
    description: str = ""
    prompt: str | None = None
    source_path: str | None = None
    default_skill_ids: list[str] = Field(default_factory=list)
    detail: str = ""
    available: bool = True

    @field_validator("id", "name", "prompt", "source_path")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        text = value.strip()
        if any(ch.isspace() for ch in text) or "/" in text or "\\" in text:
            raise ValueError("id must not contain whitespace, '/', or '\\'")
        return text

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("task_types")
    @classmethod
    def validate_task_types(cls, value: list[TaskType]) -> list[TaskType]:
        if not value:
            raise ValueError("task_types must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("task_types must be unique")
        _check_known_task_types(value)
        return value

    @field_validator("default_skill_ids")
    @classmethod
    def validate_default_skill_ids(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in value or []:
            key = (item or "").strip()
            if not key or key in seen:
                continue
            if any(ch.isspace() for ch in key) or "/" in key or "\\" in key:
                raise ValueError("default_skill_ids must not contain whitespace, '/', or '\\'")
            seen.add(key)
            deduped.append(key)
        return deduped

    @model_validator(mode="after")
    def validate_prompt_source(self) -> "RoleConfig":
        if bool(self.prompt) == bool(self.source_path):
            raise ValueError(f"role {self.id} must set exactly one of prompt or source_path")
        return self


class ContainerConfig(BaseModel):
    """Worker container configuration.

    The ``user`` field controls which UID:GID the long-lived project container
    is created as, passed straight through to ``docker.containers.run(user=...)``.
    The ``exec_user`` field controls which user task commands run as via
    Docker exec.

    - On macOS Docker Desktop, host bind mounts go through VirtioFS / gRPC-FUSE,
      which does not preserve the world-writable bit when the container's UID
      differs from the host file's owner. The worker (running as ``kali``,
      UID 1000) therefore cannot write to ``/mnt/project`` if the host dir is
      owned by a different UID (e.g. host ``jmac`` = UID 501). Set ``user`` to
      the host user's ``uid:gid`` (``id -u`` / ``id -g``) to fix.
    - On Linux Docker Engine the UID namespace is shared 1:1 with the host, so
      ``user`` is optional and the default (use the image's ``USER kali``)
      usually works.
    - Leaving ``user`` unset (``None``) preserves the prior behavior.
    """

    image: str
    dispatcher_id: str = "default"
    user: str | None = None
    exec_user: str | None = None
    network_mode: str
    completed_action: ContainerInactiveAction
    stopped_action: ContainerInactiveAction = "stop"
    cap_add: list[str] = Field(default_factory=list)
    bind_mounts: list[BindMountConfig] = Field(default_factory=list)

    @field_validator("dispatcher_id", "user", "exec_user")
    @classmethod
    def validate_user(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty or whitespace")
        if any(ch.isspace() for ch in stripped) or "/" in stripped or "\\" in stripped:
            raise ValueError("must not contain whitespace, '/', or '\\'")
        return stripped

    @model_validator(mode="after")
    def validate_bind_mounts(self) -> "ContainerConfig":
        names = [mount.name for mount in self.bind_mounts if mount.name is not None]
        if len(names) != len(set(names)):
            raise ValueError("container bind_mount names must be unique")
        container_paths = [mount.container_path for mount in self.bind_mounts]
        if len(container_paths) != len(set(container_paths)):
            raise ValueError("container bind_mount container_path values must be unique")
        return self


class RuntimeConfig(BaseModel):
    max_workers: int = Field(gt=0)
    max_running_projects: int = Field(gt=0)
    max_project_workers: int = Field(gt=0)
    interval: int = Field(gt=0)
    healthcheck_timeout: int = Field(gt=0)
    prompt_group: str = Field(min_length=1)


class SystemDatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    pool_size: int = Field(default=5, gt=0)
    max_overflow: int = Field(default=10, ge=0)
    pool_timeout: float = Field(default=30, gt=0)

    @field_validator("url")
    @classmethod
    def validate_postgresql_url(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("database.url must not be empty")
        if not text.startswith(("postgresql://", "postgresql+")):
            raise ValueError("database.url must be a PostgreSQL URL")
        return text


class SystemAuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jwt_secret: str
    dispatcher_api_token: str = ""

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("auth.jwt_secret must not be empty")
        return text


class SystemInitialAdminConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = ""
    password: str = ""


class SystemPathsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    datas_root: str
    attachments_root: str | None = None
    project_files_root: str | None = None
    worker_attachments_root: str = "/mnt/attachments"

    @field_validator("datas_root", "attachments_root", "project_files_root", "worker_attachments_root")
    @classmethod
    def validate_path_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("path values must not be empty")
        return text

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_attachments_root(self) -> str:
        return self.attachments_root or str(Path(self.datas_root) / "attachments")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_project_files_root(self) -> str:
        return self.project_files_root or str(Path(self.datas_root) / "project-files")


class SystemDispatcherConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reload_url: str = "http://cairn-dispatcher:9100/reload"
    reload_enabled: bool = True
    health_addr: str = "127.0.0.1:9100"
    leader_ttl_seconds: float = Field(default=15, gt=0)


class SystemServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    retention_loop_enabled: bool = True
    retention_interval_seconds: int = Field(default=6 * 60 * 60, ge=60)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        text = value.strip().upper()
        if not text:
            raise ValueError("server.log_level must not be empty")
        return text


class SystemConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database: SystemDatabaseConfig
    auth: SystemAuthConfig
    initial_admin: SystemInitialAdminConfig = Field(default_factory=SystemInitialAdminConfig)
    paths: SystemPathsConfig
    dispatcher: SystemDispatcherConfig = Field(default_factory=SystemDispatcherConfig)
    server: SystemServerConfig = Field(default_factory=SystemServerConfig)


class WorkerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str | None = None
    description: str = ""
    type: WorkerType
    task_types: list[TaskType]
    max_running: int = Field(gt=0)
    priority: int = Field(ge=0)
    models: list[str] = Field(default_factory=list)
    model_reasoning_effort: ReasoningEffort | None = None
    env: dict[str, str] = Field(default_factory=dict)
    available: bool = True
    detail: str = ""
    healthcheck_timeout: float | None = None
    last_health_ok: bool | None = None
    last_health_message: str = ""
    last_health_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("task_types")
    @classmethod
    def validate_task_types(cls, value: list[TaskType]) -> list[TaskType]:
        if not value:
            raise ValueError("task_types must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("task_types must be unique")
        _check_known_task_types(value)
        return value

    @field_validator("models")
    @classmethod
    def validate_models(cls, value: list[str]) -> list[str]:
        models: list[str] = []
        seen: set[str] = set()
        for item in value:
            model = item.strip()
            if not model:
                raise ValueError("models must not contain empty values")
            if model in seen:
                continue
            seen.add(model)
            models.append(model)
        return models

    @model_validator(mode="after")
    def validate_env(self) -> "WorkerConfig":
        required = WORKER_ENV_KEYS[self.type]
        missing = [key for key in required if not self.env.get(key)]
        if missing:
            raise ValueError(f"worker {self.name} missing env keys: {', '.join(missing)}")
        if self.type == "pi":
            _validate_optional_positive_int_env(self.name, self.env, "PI_MODEL_CONTEXT_WINDOW")
        if self.type == "mock":
            resolve_mock_behavior(self.name, self.env)
        return self


class DispatchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system: SystemConfig
    server: str
    server_settings: dict[str, Any] = Field(default_factory=dict)
    proxies: list[dict[str, Any]] = Field(default_factory=list)
    runtime: RuntimeConfig
    tasks: TasksConfig
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    container: ContainerConfig
    remote_support: RemoteSupportConfig = Field(default_factory=RemoteSupportConfig)
    capabilities: CapabilitiesConfig = Field(default_factory=CapabilitiesConfig)
    roles: list[RoleConfig] = Field(default_factory=list)
    common_env: dict[str, str] = Field(default_factory=dict)
    workers: list[WorkerConfig]

    @model_validator(mode="before")
    @classmethod
    def merge_common_env(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        common_env = data.get("common_env")
        if common_env is None:
            common_env = {}
        workers = data.get("workers")
        if not isinstance(common_env, dict) or not isinstance(workers, list):
            return data

        remote_env = _remote_support_env_from_raw(data.get("remote_support"))
        merged_common_env = {**common_env, **remote_env}
        merged = dict(data)
        merged_workers: list[Any] = []
        for worker in workers:
            if not isinstance(worker, dict):
                merged_workers.append(worker)
                continue
            worker_env = worker.get("env")
            if worker_env is None:
                worker_env = {}
            if not isinstance(worker_env, dict):
                merged_workers.append(worker)
                continue
            worker_copy = dict(worker)
            worker_copy["env"] = {**merged_common_env, **worker_env}
            merged_workers.append(worker_copy)
        merged["workers"] = merged_workers
        return merged

    @model_validator(mode="after")
    def validate_workers(self) -> "DispatchConfig":
        names = [worker.name for worker in self.workers]
        if len(set(names)) != len(names):
            raise ValueError("worker names must be unique")
        if not self.workers:
            raise ValueError("workers must not be empty")
        role_ids = [role.id for role in self.roles]
        if len(role_ids) != len(set(role_ids)):
            raise ValueError("roles ids must be unique")
        if self.runtime.max_project_workers > self.runtime.max_workers:
            raise ValueError("max_project_workers cannot exceed max_workers")
        return self

    @model_validator(mode="after")
    def validate_role_default_skills(self) -> "DispatchConfig":
        declared_skill_ids = {skill.id for skill in self.capabilities.skills}
        for role in self.roles:
            for skill_id in role.default_skill_ids:
                if skill_id not in declared_skill_ids:
                    raise ValueError(
                        f"role {role.id} default_skill_ids references skill {skill_id!r} "
                        f"but that id is not declared in capabilities.skills"
                    )
        return self

    @classmethod
    def load(cls, path: Path) -> "DispatchConfig":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        capabilities_path = path.with_name("dispatch.capabilities.yaml")
        capabilities_data = yaml.safe_load(capabilities_path.read_text(encoding="utf-8")) or {}
        if not isinstance(capabilities_data, dict):
            raise ValueError(f"capabilities config must be a mapping: {capabilities_path}")
        merged = dict(data)
        for key in ("remote_support", "capabilities", "roles"):
            if key in capabilities_data:
                merged[key] = capabilities_data[key]
        data = merged
        data = prepare_bind_mount_data(data, path.parent)
        data = prepare_capability_data(data, path.parent)
        data = prepare_role_data(data, path.parent)
        config = cls.model_validate(data)
        validate_prompt_resources(config.runtime.prompt_group)
        validate_capability_resources(config)
        validate_role_resources(config)
        return config


def _remote_support_env_from_raw(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    try:
        return RemoteSupportConfig.model_validate(raw).environment()
    except Exception:
        # Let the main DispatchConfig validation raise the detailed configuration error.
        return {}


def _validate_optional_positive_int_env(worker_name: str, env: dict[str, str], key: str) -> None:
    value = env.get(key)
    if value is None or not value.strip():
        return
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"worker {worker_name} env {key} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"worker {worker_name} env {key} must be greater than 0")


def prepare_bind_mount_data(data: Any, config_dir: Path) -> Any:
    if not isinstance(data, dict):
        return data
    container = data.get("container")
    if not isinstance(container, dict):
        return data
    mounts = container.get("bind_mounts")
    if mounts is None:
        return data
    if not isinstance(mounts, list):
        return data

    prepared_mounts: list[Any] = []
    for mount in mounts:
        if not isinstance(mount, dict):
            prepared_mounts.append(mount)
            continue
        mount_copy = dict(mount)
        host_path = mount_copy.get("host_path")
        if isinstance(host_path, str):
            mount_copy["host_path"] = _resolve_bind_mount_host_path(config_dir, host_path)
            _ensure_bind_mount_host_dir(mount_copy["host_path"])
        prepared_mounts.append(mount_copy)

    container_copy = dict(container)
    container_copy["bind_mounts"] = prepared_mounts
    data_copy = dict(data)
    data_copy["container"] = container_copy
    return data_copy


def prepare_capability_data(data: Any, config_dir: Path) -> Any:
    if not isinstance(data, dict):
        return data
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, dict):
        return data
    mcp_servers = capabilities.get("mcp_servers")
    skills = capabilities.get("skills")
    prepared_mcp_servers: list[Any] = []
    if isinstance(mcp_servers, list):
        for mcp in mcp_servers:
            if not isinstance(mcp, dict):
                prepared_mcp_servers.append(mcp)
                continue
            mcp_copy = dict(mcp)
            source_path = mcp_copy.get("source_path")
            if isinstance(source_path, str):
                path = Path(source_path).expanduser()
                if not path.is_absolute():
                    path = config_dir / path
                mcp_copy["source_path"] = str(path.resolve(strict=False))
            prepared_mcp_servers.append(mcp_copy)
    prepared_skills: list[Any] = []
    if isinstance(skills, list):
        for skill in skills:
            if not isinstance(skill, dict):
                prepared_skills.append(skill)
                continue
            skill_copy = dict(skill)
            source_path = skill_copy.get("source_path")
            if isinstance(source_path, str):
                path = Path(source_path).expanduser()
                if not path.is_absolute():
                    path = config_dir / path
                skill_copy["source_path"] = str(path.resolve(strict=False))
            prepared_skills.append(skill_copy)
    capabilities_copy = dict(capabilities)
    if isinstance(mcp_servers, list):
        capabilities_copy["mcp_servers"] = prepared_mcp_servers
    if isinstance(skills, list):
        capabilities_copy["skills"] = prepared_skills
    data_copy = dict(data)
    data_copy["capabilities"] = capabilities_copy
    return data_copy


def prepare_role_data(data: Any, config_dir: Path) -> Any:
    if not isinstance(data, dict):
        return data
    roles = data.get("roles")
    if not isinstance(roles, list):
        return data
    prepared_roles: list[Any] = []
    for role in roles:
        if not isinstance(role, dict):
            prepared_roles.append(role)
            continue
        role_copy = dict(role)
        source_path = role_copy.get("source_path")
        if isinstance(source_path, str):
            path = Path(source_path).expanduser()
            if not path.is_absolute():
                path = config_dir / path
            role_copy["source_path"] = str(path.resolve(strict=False))
        prepared_roles.append(role_copy)
    data_copy = dict(data)
    data_copy["roles"] = prepared_roles
    return data_copy


def _resolve_bind_mount_host_path(config_dir: Path, host_path: str) -> str:
    path = Path(host_path).expanduser()
    if not path.is_absolute():
        path = config_dir / path
    return str(path.resolve(strict=False))


def _ensure_bind_mount_host_dir(host_path: str) -> None:
    if "{project_id}" in host_path:
        root = Path(host_path.split("{project_id}", 1)[0]).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir():
            raise ValueError(f"bind mount host_path root is not a directory: {root}")
        return
    path = Path(host_path).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError(f"bind mount host_path is not a directory: {path}")


def validate_prompt_resources(prompt_group: str) -> None:
    prompts_dir = resources.files("cairn.dispatcher.prompts")
    group_dir = prompts_dir.joinpath(prompt_group)
    if not group_dir.is_dir():
        raise ValueError(f"missing prompt group: {prompt_group}")
    required_tokens = PROMPT_REQUIRED_TOKENS_BY_GROUP.get(prompt_group, DEFAULT_PROMPT_REQUIRED_TOKENS)
    for name, tokens in required_tokens.items():
        try:
            content = group_dir.joinpath(name).read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ValueError(f"prompt group {prompt_group} missing resource: {name}") from exc
        missing = [token for token in tokens if token not in content]
        if missing:
            raise ValueError(f"prompt group {prompt_group} resource {name} missing placeholders: {', '.join(missing)}")


def validate_capability_resources(config: DispatchConfig) -> None:
    for mcp in config.capabilities.mcp_servers:
        if not mcp.source_path:
            continue
        path = Path(mcp.source_path)
        if not path.exists():
            raise ValueError(f"capability mcp_server {mcp.id} source_path does not exist: {path}")
        if not path.is_dir():
            raise ValueError(f"capability mcp_server {mcp.id} source_path must be a directory: {path}")
    for skill in config.capabilities.skills:
        path = Path(skill.source_path)
        if not path.exists():
            raise ValueError(f"capability skill {skill.id} source_path does not exist: {path}")
        if not path.is_dir():
            raise ValueError(f"capability skill {skill.id} source_path must be a directory: {path}")


def validate_role_resources(config: DispatchConfig) -> None:
    for role in config.roles:
        if role.source_path is None:
            continue
        path = Path(role.source_path)
        if not path.exists():
            raise ValueError(f"role {role.id} source_path does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"role {role.id} source_path must be a file: {path}")


def resolve_mock_behavior(worker_name: str, env: dict[str, str]) -> dict[str, dict[str, Any]]:
    unknown = sorted(key for key in env if key.startswith("MOCK_") and key not in MOCK_ALLOWED_ENV_KEYS)
    if unknown:
        raise ValueError(f"worker {worker_name} has unsupported mock env keys: {', '.join(unknown)}")

    behavior: dict[str, dict[str, Any]] = {}
    for phase, allowed_outcomes in MOCK_ALLOWED_OUTCOMES.items():
        prefix = _mock_env_prefix(phase)
        payload = _parse_mock_phase_payload(worker_name, env, prefix, MOCK_DEFAULT_BEHAVIOR[phase])
        min_delay, max_delay = _parse_mock_delay_range(worker_name, prefix, payload.get("delay"))
        if max_delay < min_delay:
            raise ValueError(f"worker {worker_name} {prefix}.delay[1] must be greater than or equal to delay[0]")
        raw_outcomes = payload.get("outcomes")
        if not isinstance(raw_outcomes, dict):
            raise ValueError(f"worker {worker_name} {prefix}.outcomes must be an object")
        unknown_outcomes = sorted(set(raw_outcomes) - allowed_outcomes)
        if unknown_outcomes:
            raise ValueError(f"worker {worker_name} {prefix}.outcomes has unsupported keys: {', '.join(unknown_outcomes)}")
        outcomes: dict[str, float] = {}
        total = Decimal("0")
        for outcome in sorted(allowed_outcomes):
            weight = _parse_mock_probability(
                worker_name,
                prefix,
                raw_outcomes,
                outcome,
            )
            outcomes[outcome] = float(weight)
            total += weight
        if total != Decimal("1"):
            raise ValueError(f"worker {worker_name} {prefix}.outcomes probabilities must sum to 1.0, got {total}")
        behavior[phase] = {
            "delay": {"min": min_delay, "max": max_delay},
            "outcomes": outcomes,
        }
        rules = payload.get("rules")
        if rules is not None:
            if not isinstance(rules, list):
                raise ValueError(f"worker {worker_name} {prefix}.rules must be an array")
            normalized_rules: list[dict[str, Any]] = []
            for index, rule in enumerate(rules):
                if not isinstance(rule, dict):
                    raise ValueError(f"worker {worker_name} {prefix}.rules[{index}] must be an object")
                force = rule.get("force")
                if not isinstance(force, str) or force not in allowed_outcomes:
                    raise ValueError(
                        f"worker {worker_name} {prefix}.rules[{index}].force must be one of: {', '.join(sorted(allowed_outcomes))}"
                    )
                entry: dict[str, Any] = {"force": force}
                if "fact_ids_gte" in rule:
                    value = rule["fact_ids_gte"]
                    if not isinstance(value, int) or value < 0:
                        raise ValueError(f"worker {worker_name} {prefix}.rules[{index}].fact_ids_gte must be a non-negative integer")
                    entry["fact_ids_gte"] = value
                if "fact_ids_lte" in rule:
                    value = rule["fact_ids_lte"]
                    if not isinstance(value, int) or value < 0:
                        raise ValueError(f"worker {worker_name} {prefix}.rules[{index}].fact_ids_lte must be a non-negative integer")
                    entry["fact_ids_lte"] = value
                if "open_intents_empty" in rule:
                    value = rule["open_intents_empty"]
                    if not isinstance(value, bool):
                        raise ValueError(f"worker {worker_name} {prefix}.rules[{index}].open_intents_empty must be boolean")
                    entry["open_intents_empty"] = value
                normalized_rules.append(entry)
            behavior[phase]["rules"] = normalized_rules
    return behavior


def _mock_env_prefix(phase: str) -> str:
    return f"MOCK_{phase.upper()}"


def _parse_mock_phase_payload(worker_name: str, env: dict[str, str], key: str, default: dict[str, Any]) -> dict[str, Any]:
    raw = env.get(key)
    if raw is None:
        return json.loads(json.dumps(default))
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"worker {worker_name} {key} must be a JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError(f"worker {worker_name} {key} must be a JSON object")
    return value


def _parse_mock_delay_range(worker_name: str, key: str, value: Any) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"worker {worker_name} {key}.delay must be a two-element number array")
    min_delay = _coerce_mock_seconds(worker_name, f"{key}.delay[0]", value[0])
    max_delay = _coerce_mock_seconds(worker_name, f"{key}.delay[1]", value[1])
    return min_delay, max_delay


def _coerce_mock_seconds(worker_name: str, key: str, value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"worker {worker_name} {key} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"worker {worker_name} {key} must be a number") from exc
    if parsed < 0:
        raise ValueError(f"worker {worker_name} {key} must be non-negative")
    return parsed


def _parse_mock_probability(worker_name: str, phase_key: str, outcomes: dict[str, Any], outcome: str) -> Decimal:
    raw = outcomes.get(outcome, MOCK_DEFAULT_BEHAVIOR[phase_key.removeprefix("MOCK_").lower()]["outcomes"][outcome])
    try:
        value = Decimal(str(raw))
    except InvalidOperation as exc:
        raise ValueError(f"worker {worker_name} {phase_key}.outcomes.{outcome} must be a decimal probability") from exc
    if value < 0 or value > 1:
        raise ValueError(f"worker {worker_name} {phase_key}.outcomes.{outcome} must be between 0 and 1")
    return value
