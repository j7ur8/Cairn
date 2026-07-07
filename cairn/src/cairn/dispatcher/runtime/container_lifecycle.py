from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from cairn.dispatcher.runtime.container_access import DockerAccess
from cairn.dispatcher.runtime.docker_labels import container_labels, container_name
from cairn.dispatcher.runtime.mounts import docker_volumes
from cairn.shared.config import ContainerConfig

LOG = logging.getLogger(__name__)


class ContainerLifecycle:
    def __init__(
        self,
        *,
        config: ContainerConfig,
        access: DockerAccess,
        api_error_type: type[Exception],
        docker_exception_type: type[Exception],
        inspect_state: Callable[[str], str | None],
        log_mount_mismatches: Callable[[str, str], None],
        mount_mismatches: Callable[[str, str], list[str]],
        workspace_preflight: Callable[[str, str, ContainerConfig], None] | None = None,
    ) -> None:
        self.config = config
        self.access = access
        self.api_error_type = api_error_type
        self.docker_exception_type = docker_exception_type
        self.inspect_state = inspect_state
        self.log_mount_mismatches = log_mount_mismatches
        self.mount_mismatches = mount_mismatches
        self.workspace_preflight = workspace_preflight
        self._ensure_running_locks: dict[str, threading.Lock] = {}
        self._ensure_running_locks_guard = threading.Lock()

    def ensure_running(self, project_id: str) -> str:
        return self.ensure_running_with_config(project_id, self.config)

    def ensure_running_with_config(self, project_id: str, config: ContainerConfig) -> str:
        name = container_name(project_id)
        with self._ensure_running_lock(name):
            return self._ensure_running_locked(project_id, name, config)

    def _ensure_running_locked(self, project_id: str, name: str, config: ContainerConfig) -> str:
        state = self.inspect_state(name)
        if state == "running":
            if self._recreate_if_config_mismatch(name, project_id, config):
                return self._create_container(project_id, name, config)
            LOG.debug("container already running project=%s container=%s", project_id, name)
            self._workspace_preflight(name, project_id, config)
            return name
        if state is not None:
            if self._recreate_if_config_mismatch(name, project_id, config):
                return self._create_container(project_id, name, config)
            LOG.info("starting existing container project=%s container=%s state=%s", project_id, name, state)
            self.start_existing(name)
            self._workspace_preflight(name, project_id, config)
            return name
        LOG.info("creating container project=%s container=%s image=%s", project_id, name, config.image)
        return self._create_container(project_id, name, config)

    def _create_container(self, project_id: str, name: str, config: ContainerConfig | None = None) -> str:
        effective_config = config or self.config
        try:
            self.access.client.containers.run(
                effective_config.image,
                ["sleep", "infinity"],
                detach=True,
                name=name,
                network_mode=effective_config.network_mode,
                cap_add=effective_config.cap_add or None,
                volumes=docker_volumes(effective_config, project_id) or None,
                user=effective_config.user,
                labels=container_labels(project_id),
                mem_limit=effective_config.mem_limit,
                pids_limit=effective_config.pids_limit,
                nano_cpus=effective_config.nano_cpus,
            )
            LOG.info("created container project=%s container=%s", project_id, name)
            self._workspace_preflight(name, project_id, effective_config)
            return name
        except self.api_error_type as exc:
            if not self.is_name_conflict(exc):
                raise RuntimeError(f"failed to create container {name}: {exc}") from exc
        LOG.info("container name conflict, reusing existing container project=%s container=%s", project_id, name)
        state = self.inspect_state(name)
        if state == "running":
            if self._recreate_if_config_mismatch(name, project_id, effective_config):
                return self._create_container(project_id, name, effective_config)
            self._workspace_preflight(name, project_id, effective_config)
            return name
        if state is not None:
            if self._recreate_if_config_mismatch(name, project_id, effective_config):
                return self._create_container(project_id, name, effective_config)
            LOG.info("starting conflicted existing container project=%s container=%s state=%s", project_id, name, state)
            self.start_existing(name)
            self._workspace_preflight(name, project_id, effective_config)
            return name
        raise RuntimeError(f"failed to create container {name}")

    def create_named_container(
        self,
        *,
        project_id: str,
        name: str,
        config: ContainerConfig | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        effective_config = config or self.config
        self.remove_container(name, force=True)
        try:
            self.access.client.containers.run(
                effective_config.image,
                ["sleep", "infinity"],
                detach=True,
                name=name,
                network_mode=effective_config.network_mode,
                cap_add=effective_config.cap_add or None,
                volumes=docker_volumes(effective_config, project_id) or None,
                user=effective_config.user,
                labels=labels or container_labels(project_id),
                mem_limit=effective_config.mem_limit,
                pids_limit=effective_config.pids_limit,
                nano_cpus=effective_config.nano_cpus,
            )
            LOG.info("created named container project=%s container=%s", project_id, name)
            self._workspace_preflight(name, project_id, effective_config)
            return name
        except self.docker_exception_type as exc:
            raise RuntimeError(f"failed to create container {name}: {exc}") from exc

    def _recreate_if_config_mismatch(self, name: str, project_id: str, config: ContainerConfig) -> bool:
        mismatches = self._mount_mismatches(name, project_id, config)
        if not mismatches:
            return False
        self._log_mount_mismatches(name, project_id, config)
        if not any(_requires_container_recreate(mismatch) for mismatch in mismatches):
            return False
        LOG.info(
            "removing container with stale config project=%s container=%s mismatches=%s",
            project_id,
            name,
            len(mismatches),
        )
        self.remove_container(name, force=True)
        return True

    def _mount_mismatches(self, name: str, project_id: str, config: ContainerConfig) -> list[str]:
        try:
            return self.mount_mismatches(name, project_id, config)
        except TypeError:
            return self.mount_mismatches(name, project_id)  # type: ignore[misc]

    def _log_mount_mismatches(self, name: str, project_id: str, config: ContainerConfig) -> None:
        try:
            self.log_mount_mismatches(name, project_id, config)
        except TypeError:
            self.log_mount_mismatches(name, project_id)  # type: ignore[misc]

    def _workspace_preflight(self, name: str, project_id: str, config: ContainerConfig) -> None:
        if self.workspace_preflight is None:
            return
        self.workspace_preflight(name, project_id, config)

    def create_startup_container(self, name: str, project_id: str) -> str:
        LOG.debug("creating startup healthcheck container container=%s image=%s", name, self.config.image)
        self.remove_container(name, force=True)
        try:
            self.access.client.containers.run(
                self.config.image,
                ["sleep", "infinity"],
                detach=True,
                name=name,
                network_mode=self.config.network_mode,
                cap_add=self.config.cap_add or None,
                volumes=docker_volumes(self.config, project_id) or None,
                user=self.config.user,
                labels=container_labels(project_id, startup=True),
                mem_limit=self.config.mem_limit,
                pids_limit=self.config.pids_limit,
                nano_cpus=self.config.nano_cpus,
            )
        except self.docker_exception_type as exc:
            raise RuntimeError(f"failed to create startup container {name}: {exc}") from exc
        return name

    def inspect_state_value(self, name: str) -> str | None:
        container = self.access.get_container(name)
        if container is None:
            return None
        try:
            container.reload()
        except self.docker_exception_type as exc:
            raise RuntimeError(f"failed to inspect container {name}: {exc}") from exc
        state = container.attrs.get("State", {}).get("Status")
        return str(state) if state else None

    def remove_container(self, name: str, *, force: bool = True) -> None:
        container = self.access.get_container(name)
        if container is None:
            return
        try:
            container.remove(force=force)
        except self.access.not_found_type:
            return
        except self.docker_exception_type as exc:
            LOG.warning("failed to remove container=%s error=%s", name, exc)

    def start_existing(self, name: str) -> None:
        LOG.debug("starting container=%s", name)
        container = self.access.require_container(name)
        try:
            container.start()
            return
        except self.docker_exception_type as exc:
            if self.inspect_state(name) == "running":
                return
            raise RuntimeError(f"failed to start container {name}: {exc}") from exc

    def _ensure_running_lock(self, name: str) -> threading.Lock:
        with self._ensure_running_locks_guard:
            lock = self._ensure_running_locks.get(name)
            if lock is None:
                lock = threading.Lock()
                self._ensure_running_locks[name] = lock
            return lock

    @staticmethod
    def is_name_conflict(exc: Exception) -> bool:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        explanation = str(getattr(exc, "explanation", "") or exc)
        return status_code == 409 or "is already in use" in explanation


def _requires_container_recreate(mismatch: str) -> bool:
    return (
        mismatch.startswith("image mismatch ")
        or mismatch.startswith("missing ")
        or " source mismatch " in mismatch
        or " mode mismatch " in mismatch
    )
