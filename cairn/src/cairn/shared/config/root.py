from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from cairn.shared.config.capability_models import CapabilitiesConfig
from cairn.shared.config.resource_root import ResourceConfig
from cairn.shared.config.role_models import RoleConfig
from cairn.shared.config.server_models import ServerResourceConfig
from cairn.shared.config.system_models import DispatcherConfig, RuntimeConfig, ServerConfig, SystemConfig
from cairn.shared.config.task_models import ObservabilityConfig, TasksConfig
from cairn.shared.config.worker_models import ContainerConfig, WorkerConfig, WorkerPoolConfig, WorkerRuntimeConfig


class DispatchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: ServerConfig
    dispatcher: DispatcherConfig
    tasks: TasksConfig
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    worker_runtime: WorkerRuntimeConfig
    worker_pool: WorkerPoolConfig
    resources: ResourceConfig = Field(default_factory=ResourceConfig)

    @model_validator(mode="before")
    @classmethod
    def merge_common_env(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        worker_runtime = data.get("worker_runtime")
        worker_pool = data.get("worker_pool")
        if not isinstance(worker_runtime, dict) or not isinstance(worker_pool, dict):
            return data
        common_env = worker_runtime.get("common_env") or {}
        workers = worker_pool.get("workers")
        if not isinstance(common_env, dict) or not isinstance(workers, list):
            return data

        merged_common_env = {
            **common_env,
            "CAIRN_SERVER_URL": str((data.get("server") or {}).get("base_url") or ""),
            "CAIRN_API_TOKEN": str(((data.get("server") or {}).get("auth") or {}).get("dispatcher_api_token") or ""),
        }
        pool_copy = dict(worker_pool)
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
        pool_copy["workers"] = merged_workers
        merged = dict(data)
        merged["worker_pool"] = pool_copy
        return merged

    @model_validator(mode="after")
    def validate_limits_and_roles(self) -> DispatchConfig:
        if self.runtime.max_project_workers > self.runtime.max_workers:
            raise ValueError("max_project_workers cannot exceed max_workers")
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
    def load(cls, path: Path) -> DispatchConfig:
        from cairn.shared.config.loader import load_dispatch_config

        return load_dispatch_config(path)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def server_url(self) -> str:
        return self.server.base_url

    @computed_field  # type: ignore[prop-decorator]
    @property
    def system(self) -> SystemConfig:
        return SystemConfig.from_sections(self.server, self.dispatcher)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def runtime(self) -> RuntimeConfig:
        return self.dispatcher.runtime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def container(self) -> ContainerConfig:
        return self.worker_runtime.runner

    @computed_field  # type: ignore[prop-decorator]
    @property
    def common_env(self) -> dict[str, str]:
        return self.worker_runtime.common_env

    @computed_field  # type: ignore[prop-decorator]
    @property
    def workers(self) -> list[WorkerConfig]:
        return self.worker_pool.workers

    @computed_field  # type: ignore[prop-decorator]
    @property
    def capabilities(self) -> CapabilitiesConfig:
        return self.resources.capabilities

    @computed_field  # type: ignore[prop-decorator]
    @property
    def roles(self) -> list[RoleConfig]:
        return self.resources.roles

    @computed_field  # type: ignore[prop-decorator]
    @property
    def servers(self) -> list[ServerResourceConfig]:
        return self.resources.servers
