from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


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
    host_datas_root: str | None = None
    attachments_root: str | None = None
    project_files_root: str | None = None
    worker_attachments_root: str = "/home/kali/workspace/attachments"

    @field_validator(
        "datas_root",
        "host_datas_root",
        "attachments_root",
        "project_files_root",
        "worker_attachments_root",
    )
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_host_datas_root(self) -> str:
        return self.host_datas_root or self.datas_root

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_host_attachments_root(self) -> str:
        return str(Path(self.resolved_host_datas_root) / "attachments")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_host_project_files_root(self) -> str:
        return str(Path(self.resolved_host_datas_root) / "project-files")


class ServerLogConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str = "INFO"
    format: Literal["text", "json"] = "text"

    @field_validator("level")
    @classmethod
    def validate_level(cls, value: str) -> str:
        text = value.strip().upper()
        if not text:
            raise ValueError("server.log.level must not be empty")
        return text


class ServerRetentionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    interval_seconds: int = Field(default=6 * 60 * 60, ge=60)


class ServerSettingsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_timeout: int = Field(gt=0)
    reason_timeout: int = Field(gt=0)


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    database: SystemDatabaseConfig
    auth: SystemAuthConfig
    initial_admin: SystemInitialAdminConfig = Field(default_factory=SystemInitialAdminConfig)
    paths: SystemPathsConfig
    log: ServerLogConfig = Field(default_factory=ServerLogConfig)
    retention: ServerRetentionConfig = Field(default_factory=ServerRetentionConfig)
    settings: ServerSettingsConfig

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("server.base_url must not be empty")
        return text.rstrip("/")


class DispatcherReloadConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = "http://cairn-dispatcher:9100/reload"
    enabled: bool = True


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_workers: int = Field(gt=0)
    max_running_projects: int = Field(gt=0)
    max_project_workers: int = Field(gt=0)
    interval: int = Field(gt=0)
    healthcheck_timeout: int = Field(gt=0)


class DispatcherConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    health_addr: str = "127.0.0.1:9100"
    reload: DispatcherReloadConfig = Field(default_factory=DispatcherReloadConfig)
    runtime: RuntimeConfig


class SystemDispatcherConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reload_url: str = "http://cairn-dispatcher:9100/reload"
    reload_enabled: bool = True
    health_addr: str = "127.0.0.1:9100"


class SystemServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    retention_loop_enabled: bool = True
    retention_interval_seconds: int = Field(default=6 * 60 * 60, ge=60)


class SystemConfig(BaseModel):
    """Runtime view consumed by server-side code.

    The YAML no longer has a top-level ``system`` key, but server code still
    benefits from this grouped runtime shape.
    """

    model_config = ConfigDict(extra="forbid")

    database: SystemDatabaseConfig
    auth: SystemAuthConfig
    initial_admin: SystemInitialAdminConfig = Field(default_factory=SystemInitialAdminConfig)
    paths: SystemPathsConfig
    dispatcher: SystemDispatcherConfig = Field(default_factory=SystemDispatcherConfig)
    server: SystemServerConfig = Field(default_factory=SystemServerConfig)

    @classmethod
    def from_sections(cls, server: ServerConfig, dispatcher: DispatcherConfig) -> SystemConfig:
        return cls(
            database=server.database,
            auth=server.auth,
            initial_admin=server.initial_admin,
            paths=server.paths,
            dispatcher=SystemDispatcherConfig(
                reload_url=dispatcher.reload.url,
                reload_enabled=dispatcher.reload.enabled,
                health_addr=dispatcher.health_addr,
            ),
            server=SystemServerConfig(
                log_level=server.log.level,
                log_format=server.log.format,
                retention_loop_enabled=server.retention.enabled,
                retention_interval_seconds=server.retention.interval_seconds,
            ),
        )
