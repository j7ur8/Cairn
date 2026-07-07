from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cairn.shared.config.constants import (
    WORKER_ENV_KEYS,
    ContainerInactiveAction,
    ReasoningEffort,
    TaskType,
    WorkerType,
    _check_known_task_types,
)
from cairn.shared.config.mock_behavior import resolve_mock_behavior


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


class ContainerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: str
    user: str | None = None
    exec_user: str | None = None
    network_mode: str
    completed_action: ContainerInactiveAction
    stopped_action: ContainerInactiveAction = "stop"
    cap_add: list[str] = Field(default_factory=list)
    bind_mounts: list[BindMountConfig] = Field(default_factory=list)
    mem_limit: str | None = None
    """Memory limit for the container, e.g. ``2g``. Passed directly to the
    Docker API :meth:`~docker.api.container.ContainerApiMixin.create_host_config`
    ``mem_limit`` kwarg. When ``None`` (the default), Docker imposes no limit."""
    pids_limit: int | None = None
    """Maximum number of processes inside the container (``--pids-limit``).
    When ``None`` (the default), Docker imposes no limit."""
    nano_cpus: int | None = None
    """CPU quota in units of 1e-9 CPUs, passed directly to the Docker API
    ``nano_cpus`` kwarg.  e.g. 1_500_000_000 = 1.5 CPUs.  When ``None``
    (the default), Docker imposes no CPU limit."""

    @field_validator("user", "exec_user")
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
    def validate_bind_mounts(self) -> ContainerConfig:
        names = [mount.name for mount in self.bind_mounts if mount.name is not None]
        if len(names) != len(set(names)):
            raise ValueError("container bind_mount names must be unique")
        container_paths = [mount.container_path for mount in self.bind_mounts]
        if len(container_paths) != len(set(container_paths)):
            raise ValueError("container bind_mount container_path values must be unique")
        return self


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
    def validate_env(self) -> WorkerConfig:
        required = WORKER_ENV_KEYS[self.type]
        missing = [key for key in required if not self.env.get(key)]
        if missing:
            raise ValueError(f"worker {self.name} missing env keys: {', '.join(missing)}")
        if self.type == "mock":
            resolve_mock_behavior(self.name, self.env)
        return self


class CloakNoVncConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    host: str = "127.0.0.1"

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("novnc.host must not be empty")
        return text


class CloakSidecarConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: str
    slots: int = Field(default=2, gt=0, le=16)
    novnc: CloakNoVncConfig = Field(default_factory=CloakNoVncConfig)
    profile_root: str

    @field_validator("image", "profile_root")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class ToolSidecarConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: str
    network_mode: str
    enabled: bool = True
    user: str | None = None
    exec_user: str | None = None
    cap_add: list[str] = Field(default_factory=list)
    bind_mounts: list[BindMountConfig] = Field(default_factory=list)
    mem_limit: str | None = None
    pids_limit: int | None = None
    nano_cpus: int | None = None

    @field_validator("image", "network_mode")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("user", "exec_user")
    @classmethod
    def validate_user(cls, value: str | None) -> str | None:
        return ContainerConfig.validate_user(value)

    @model_validator(mode="after")
    def validate_bind_mounts(self) -> ToolSidecarConfig:
        names = [mount.name for mount in self.bind_mounts if mount.name is not None]
        if len(names) != len(set(names)):
            raise ValueError("tool sidecar bind_mount names must be unique")
        container_paths = [mount.container_path for mount in self.bind_mounts]
        if len(container_paths) != len(set(container_paths)):
            raise ValueError("tool sidecar bind_mount container_path values must be unique")
        return self

    def as_container_config(self) -> ContainerConfig:
        return ContainerConfig(
            image=self.image,
            user=self.user,
            exec_user=self.exec_user,
            network_mode=self.network_mode,
            completed_action="remove",
            stopped_action="remove",
            cap_add=list(self.cap_add),
            bind_mounts=list(self.bind_mounts),
            mem_limit=self.mem_limit,
            pids_limit=self.pids_limit,
            nano_cpus=self.nano_cpus,
        )


class ToolSidecarsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kali: ToolSidecarConfig | None = None
    metasploit: ToolSidecarConfig | None = None


class WorkerRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runner: ContainerConfig
    common_env: dict[str, str] = Field(default_factory=dict)
    tool_sidecars: ToolSidecarsConfig = Field(default_factory=ToolSidecarsConfig)
    cloak_sidecar: CloakSidecarConfig | None = None

    @property
    def container(self) -> ContainerConfig:
        return self.runner


class WorkerPoolConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workers: list[WorkerConfig]

    @model_validator(mode="after")
    def validate_workers(self) -> WorkerPoolConfig:
        names = [worker.name for worker in self.workers]
        if len(set(names)) != len(names):
            raise ValueError("worker names must be unique")
        if not self.workers:
            raise ValueError("workers must not be empty")
        return self


def prepare_bind_mount_data(data: Any, config_dir: Path) -> Any:
    if not isinstance(data, dict):
        return data
    worker_runtime = data.get("worker_runtime")
    if not isinstance(worker_runtime, dict):
        return data
    runner = worker_runtime.get("runner")
    if not isinstance(runner, dict):
        return data
    mounts = runner.get("bind_mounts")
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
        prepared_mounts.append(mount_copy)

    runner_copy = dict(runner)
    runner_copy["bind_mounts"] = prepared_mounts
    runtime_copy = dict(worker_runtime)
    runtime_copy["runner"] = runner_copy

    sidecars = runtime_copy.get("tool_sidecars")
    if isinstance(sidecars, dict):
        prepared_sidecars: dict[str, Any] = {}
        for key, raw_sidecar in sidecars.items():
            if not isinstance(raw_sidecar, dict):
                prepared_sidecars[key] = raw_sidecar
                continue
            sidecar_copy = dict(raw_sidecar)
            sidecar_mounts = sidecar_copy.get("bind_mounts")
            if isinstance(sidecar_mounts, list):
                sidecar_prepared_mounts: list[Any] = []
                for mount in sidecar_mounts:
                    if not isinstance(mount, dict):
                        sidecar_prepared_mounts.append(mount)
                        continue
                    mount_copy = dict(mount)
                    host_path = mount_copy.get("host_path")
                    if isinstance(host_path, str):
                        mount_copy["host_path"] = _resolve_bind_mount_host_path(config_dir, host_path)
                    sidecar_prepared_mounts.append(mount_copy)
                sidecar_copy["bind_mounts"] = sidecar_prepared_mounts
            prepared_sidecars[key] = sidecar_copy
        runtime_copy["tool_sidecars"] = prepared_sidecars

    data_copy = dict(data)
    data_copy["worker_runtime"] = runtime_copy
    return data_copy


def _resolve_bind_mount_host_path(config_dir: Path, host_path: str) -> str:
    expanded = os.path.expandvars(host_path)
    unresolved = _UNRESOLVED_ENV_RE.search(expanded)
    if unresolved:
        raise ValueError(
            "container bind_mount host_path contains unresolved environment variable "
            f"{unresolved.group(0)!r}; set it before loading config"
        )
    path = Path(os.path.expandvars(expanded)).expanduser()
    if not path.is_absolute():
        path = config_dir / path
    return str(path.resolve(strict=False))


_UNRESOLVED_ENV_RE = re.compile(r"\$(?:\{[^}]+\}|[A-Za-z_][A-Za-z0-9_]*)")
