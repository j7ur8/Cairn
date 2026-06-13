from __future__ import annotations

import logging
from collections.abc import Callable

from cairn.dispatcher.runtime.cleanup_policy import needs_cleanup_for_action
from cairn.dispatcher.runtime.container_access import DockerAccess
from cairn.dispatcher.runtime.docker_labels import LABEL_MANAGED, is_startup_container
from cairn.shared.config import ContainerConfig

LOG = logging.getLogger(__name__)


class ContainerCleanup:
    def __init__(
        self,
        *,
        config: ContainerConfig,
        access: DockerAccess,
        docker_exception_type: type[Exception],
        not_found_type: type[Exception],
        prefix: str,
        inspect_state: Callable[[str], str | None],
        container_name: Callable[[str], str],
    ) -> None:
        self.config = config
        self.access = access
        self.docker_exception_type = docker_exception_type
        self.not_found_type = not_found_type
        self.prefix = prefix
        self.inspect_state = inspect_state
        self.container_name = container_name

    def cleanup_completed(self, project_id: str) -> bool:
        name = self.container_name(project_id)
        state = self.inspect_state(name)
        if state is None:
            return True
        container = self.access.require_container(name)
        if self.config.completed_action == "remove":
            LOG.info("removing completed project container project=%s container=%s", project_id, name)
            return self._remove(name, container)
        if state == "running":
            LOG.info("stopping completed project container project=%s container=%s", project_id, name)
            return self._stop(name, container)
        return True

    def cleanup_stopped(self, project_id: str) -> bool:
        name = self.container_name(project_id)
        state = self.inspect_state(name)
        if state is None:
            return True
        container = self.access.require_container(name)
        if self.config.stopped_action == "remove":
            LOG.info("removing stopped project container project=%s container=%s", project_id, name)
            return self._remove(name, container, stopped=True)
        if state != "running":
            return True
        LOG.info("stopping stopped project container project=%s container=%s", project_id, name)
        return self._stop(name, container, stopped=True)

    def cleanup_orphan(self, name: str) -> bool:
        state = self.inspect_state(name)
        if state is None:
            return True
        LOG.info("removing orphan project container container=%s state=%s", name, state)
        container = self.access.require_container(name)
        return self._remove(name, container, orphan=True)

    def managed_container_names(self) -> list[str]:
        try:
            containers = self.access.client.containers.list(
                all=True,
                filters={"label": [f"{LABEL_MANAGED}=true"]},
            )
        except self.docker_exception_type as exc:
            LOG.warning("failed to list managed containers error=%s", exc)
            return []
        return sorted(
            container.name
            for container in containers
            if container.name.startswith(self.prefix) and not is_startup_container(container)
        )

    def needs_completed_cleanup(self, project_id: str) -> bool:
        state = self.inspect_state(self.container_name(project_id))
        return needs_cleanup_for_action(state, self.config.completed_action)

    def needs_orphan_cleanup(self, name: str) -> bool:
        return self.inspect_state(name) is not None

    def needs_stopped_cleanup(self, project_id: str) -> bool:
        state = self.inspect_state(self.container_name(project_id))
        return needs_cleanup_for_action(state, self.config.stopped_action)

    def _remove(self, name: str, container, *, stopped: bool = False, orphan: bool = False) -> bool:
        try:
            container.remove(force=True)
        except self.not_found_type:
            return True
        except self.docker_exception_type as exc:
            if stopped:
                LOG.warning("failed to remove stopped project container=%s error=%s", name, exc)
            elif orphan:
                LOG.warning("failed to remove orphan container=%s error=%s", name, exc)
            else:
                LOG.warning("failed to remove container=%s error=%s", name, exc)
            return False
        return self.inspect_state(name) is None

    def _stop(self, name: str, container, *, stopped: bool = False) -> bool:
        try:
            container.stop(timeout=1)
        except self.not_found_type:
            return True
        except self.docker_exception_type as exc:
            if stopped:
                LOG.warning("failed to stop stopped project container=%s error=%s", name, exc)
            else:
                LOG.warning("failed to stop container=%s error=%s", name, exc)
            return False
        return self.inspect_state(name) != "running"
