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
        proxy_environment: Callable[[str], dict[str, str]],
        inspect_state: Callable[[str], str | None],
        log_mount_mismatches: Callable[[str, str], None],
    ) -> None:
        self.config = config
        self.access = access
        self.api_error_type = api_error_type
        self.docker_exception_type = docker_exception_type
        self.proxy_environment = proxy_environment
        self.inspect_state = inspect_state
        self.log_mount_mismatches = log_mount_mismatches
        self._ensure_running_locks: dict[str, threading.Lock] = {}
        self._ensure_running_locks_guard = threading.Lock()

    def ensure_running(self, project_id: str) -> str:
        name = container_name(project_id)
        with self._ensure_running_lock(name):
            return self._ensure_running_locked(project_id, name)

    def _ensure_running_locked(self, project_id: str, name: str) -> str:
        state = self.inspect_state(name)
        if state == "running":
            self.log_mount_mismatches(name, project_id)
            LOG.debug("container already running project=%s container=%s", project_id, name)
            return name
        if state is not None:
            self.log_mount_mismatches(name, project_id)
            LOG.info("starting existing container project=%s container=%s state=%s", project_id, name, state)
            self.start_existing(name)
            return name
        LOG.info("creating container project=%s container=%s image=%s", project_id, name, self.config.image)
        try:
            self.access.client.containers.run(
                self.config.image,
                ["sleep", "infinity"],
                detach=True,
                name=name,
                network_mode=self.config.network_mode,
                cap_add=self.config.cap_add or None,
                volumes=docker_volumes(self.config, project_id) or None,
                environment=self.proxy_environment(project_id) or None,
                user=self.config.user,
                labels=container_labels(project_id),
                mem_limit=self.config.mem_limit,
                pids_limit=self.config.pids_limit,
                nano_cpus=self.config.nano_cpus,
            )
            LOG.info("created container project=%s container=%s", project_id, name)
            return name
        except self.api_error_type as exc:
            if not self.is_name_conflict(exc):
                raise RuntimeError(f"failed to create container {name}: {exc}") from exc
        LOG.info("container name conflict, reusing existing container project=%s container=%s", project_id, name)
        state = self.inspect_state(name)
        if state == "running":
            self.log_mount_mismatches(name, project_id)
            return name
        if state is not None:
            self.log_mount_mismatches(name, project_id)
            LOG.info("starting conflicted existing container project=%s container=%s state=%s", project_id, name, state)
            self.start_existing(name)
            return name
        raise RuntimeError(f"failed to create container {name}")

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
                environment=self.proxy_environment(project_id) or None,
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
