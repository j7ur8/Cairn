from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docker.models.containers import Container

try:
    import docker
    from docker.errors import APIError, DockerException, NotFound
except ModuleNotFoundError:  # Allows scheduler pure logic to import without Docker SDK.
    docker = None

    class DockerException(Exception):  # type: ignore[no-redef]
        pass

    class APIError(DockerException):  # type: ignore[no-redef]
        pass

    class NotFound(DockerException):  # type: ignore[no-redef]
        pass

from cairn.dispatcher.runtime.archive_writer import directory_archive, text_file_archive
from cairn.dispatcher.runtime.bind_mount_validation import (
    mount_mismatches as inspect_mount_mismatches,
)
from cairn.dispatcher.runtime.bind_mount_validation import (
    validate_bind_mounts as validate_config_bind_mounts,
)
from cairn.dispatcher.runtime.container_access import DockerAccess
from cairn.dispatcher.runtime.container_cleanup import ContainerCleanup
from cairn.dispatcher.runtime.container_exec import ContainerExec
from cairn.dispatcher.runtime.container_files import ContainerFiles
from cairn.dispatcher.runtime.container_lifecycle import ContainerLifecycle
from cairn.dispatcher.runtime.docker_labels import (
    CONTAINER_PREFIX,
    LABEL_MANAGED,
    LABEL_KIND,
    LABEL_PHASE,
    STARTUP_CONTAINER_NAME,
    STARTUP_PROJECT_ID,
    container_name,
    container_labels,
    is_startup_container,
    runner_container_name,
)
from cairn.dispatcher.runtime.mounts import docker_volumes, render_bind_mounts
from cairn.dispatcher.runtime.process import ManagedProcess
from cairn.dispatcher.runtime.workspace_preflight import WorkspacePreflight
from cairn.shared.config import ContainerConfig

LOG = logging.getLogger(__name__)


class ContainerManager:
    _PREFIX = CONTAINER_PREFIX
    _STARTUP_NAME = STARTUP_CONTAINER_NAME
    _STARTUP_PROJECT_ID = STARTUP_PROJECT_ID
    _LABEL_MANAGED = LABEL_MANAGED

    def __init__(
        self,
        config: ContainerConfig,
    ):
        self._config = config
        if docker is None:
            raise RuntimeError("Docker SDK is required for container runtime operations")
        self._client = docker.from_env()
        self._logged_mount_mismatches: set[tuple[str, str]] = set()
        self._access = DockerAccess(
            self._client,
            docker_exception_type=DockerException,
            not_found_type=NotFound,
        )
        self._workspace_preflight = WorkspacePreflight(
            access=self._access,
            docker_exception_type=DockerException,
        )
        self._lifecycle = ContainerLifecycle(
            config=self._config,
            access=self._access,
            api_error_type=APIError,
            docker_exception_type=DockerException,
            inspect_state=self.inspect_state,
            log_mount_mismatches=self.log_mount_mismatches,
            mount_mismatches=self.mount_mismatches,
            workspace_preflight=self._workspace_preflight.run,
        )
        self._cleanup = ContainerCleanup(
            config=self._config,
            access=self._access,
            docker_exception_type=DockerException,
            not_found_type=NotFound,
            prefix=self._PREFIX,
            inspect_state=self.inspect_state,
            container_name=self.container_name,
        )
        self._files = ContainerFiles(access=self._access, docker_exception_type=DockerException)
        self._exec = ContainerExec(
            config=self._config,
            access=self._access,
            require_container=lambda name: self._require_container(name),
        )

    def close(self) -> None:
        self._client.close()

    def container_name(self, project_id: str) -> str:
        return container_name(project_id)

    def ensure_running(self, project_id: str, container_config: ContainerConfig | None = None) -> str:
        if container_config is None:
            return self._lifecycle.ensure_running(project_id)
        return self._lifecycle.ensure_running_with_config(project_id, container_config)

    def create_runner_container(
        self,
        *,
        project_id: str,
        task_id: str,
        phase: str,
        container_config: ContainerConfig | None = None,
    ) -> str:
        name = runner_container_name(project_id, task_id)
        labels = container_labels(project_id, kind="runner", task_id=task_id, phase=phase)
        labels[LABEL_KIND] = "runner"
        labels[LABEL_PHASE] = phase
        return self._lifecycle.create_named_container(
            project_id=project_id,
            name=name,
            config=container_config or self._config,
            labels=labels,
        )

    def create_startup_container(self) -> str:
        name = self._STARTUP_NAME
        return self._lifecycle.create_startup_container(name, self._STARTUP_PROJECT_ID)

    def validate_bind_mounts(
        self,
        container_name: str,
        project_id: str,
        container_config: ContainerConfig | None = None,
    ) -> list[str]:
        return validate_config_bind_mounts(
            config=container_config or self._config,
            project_id=project_id,
            probe=lambda container_path, read_only: self._probe_bind_mount(container_name, container_path, read_only),
        )

    def log_managed_container_mount_mismatches(self) -> None:
        for name in self.managed_container_names():
            project_id = name.removeprefix(self._PREFIX)
            self.log_mount_mismatches(name, project_id)

    def log_mount_mismatches(
        self,
        container_name: str,
        project_id: str,
        container_config: ContainerConfig | None = None,
    ) -> None:
        mismatches = self.mount_mismatches(container_name, project_id, container_config)
        for mismatch in mismatches:
            log_key = (container_name, mismatch)
            if log_key in self._logged_mount_mismatches:
                continue
            self._logged_mount_mismatches.add(log_key)
            LOG.warning("container bind mount mismatch container=%s project=%s %s", container_name, project_id, mismatch)

    def mount_mismatches(
        self,
        container_name: str,
        project_id: str,
        container_config: ContainerConfig | None = None,
    ) -> list[str]:
        return inspect_mount_mismatches(
            config=container_config or self._config,
            project_id=project_id,
            container=self._get_container(container_name),
            docker_exception_type=DockerException,
        )

    def inspect_state(self, name: str) -> str | None:
        return self._lifecycle.inspect_state_value(name)

    def cleanup_completed(self, project_id: str) -> bool:
        return self._cleanup.cleanup_completed(project_id)

    def cleanup_stopped(self, project_id: str) -> bool:
        return self._cleanup.cleanup_stopped(project_id)

    def cleanup_orphan(self, name: str) -> bool:
        return self._cleanup.cleanup_orphan(name)

    def managed_container_names(self) -> list[str]:
        return self._cleanup.managed_container_names()

    def _is_startup_container(self, container: Container) -> bool:
        return is_startup_container(container)

    def needs_completed_cleanup(self, project_id: str) -> bool:
        return self._cleanup.needs_completed_cleanup(project_id)

    def needs_orphan_cleanup(self, name: str) -> bool:
        return self._cleanup.needs_orphan_cleanup(name)

    def needs_stopped_cleanup(self, project_id: str) -> bool:
        return self._cleanup.needs_stopped_cleanup(project_id)

    def build_exec_process(
        self,
        container_name: str,
        env: dict[str, str],
        command: list[str],
        timeout_seconds: int | None = None,
        kill_after_seconds: int = 5,
        workdir: str | None = None,
        tty: bool = False,
        on_output: Callable[[str, str], None] | None = None,
    ) -> ManagedProcess:
        return self._exec.build_exec_process(
            container_name,
            env,
            command,
            timeout_seconds=timeout_seconds,
            kill_after_seconds=kill_after_seconds,
            workdir=workdir,
            tty=tty,
            on_output=on_output,
        )

    def write_text_file(self, container_name: str, path: str, content: str) -> None:
        self._files.write_text_file(container_name, path, content)

    def write_directory(self, container_name: str, path: str, source: Path) -> None:
        self._files.write_directory(container_name, path, source)

    def remove_container(self, name: str, *, force: bool = True) -> None:
        self._lifecycle.remove_container(name, force=force)

    def _start_existing(self, name: str, *, project_id: str | None = None) -> None:
        self._lifecycle.start_existing(name)

    def _get_container(self, name: str) -> Container | None:
        return self._access.get_container(name)

    def _require_container(self, name: str) -> Container:
        return self._access.require_container(name)

    def _docker_volumes(self, project_id: str) -> dict[str, dict[str, str]]:
        return docker_volumes(self._config, project_id)

    def _render_bind_mounts(self, project_id: str) -> list[dict[str, object]]:
        return self._render_bind_mounts_for(self._config, project_id)

    @staticmethod
    def _render_bind_mounts_for(
        config: ContainerConfig, project_id: str,
    ) -> list[dict[str, object]]:
        return render_bind_mounts(config, project_id)

    def _probe_bind_mount(self, container_name: str, container_path: str, read_only: bool) -> str | None:
        script = (
            'target="$1"\n'
            'mode="$2"\n'
            'if [ ! -d "$target" ]; then echo "container path is not a directory: $target" >&2; exit 2; fi\n'
            'if [ "$mode" = "rw" ]; then\n'
            '  probe="$target/.cairn-write-test-$(date +%s)-$$"\n'
            '  printf ok > "$probe" || exit 3\n'
            '  rm -f "$probe" || exit 4\n'
            'fi\n'
        )
        container = self._require_container(container_name)
        try:
            result = container.exec_run(
                ["/bin/sh", "-lc", script, "--", container_path, "ro" if read_only else "rw"],
                stdout=True,
                stderr=True,
            )
        except DockerException as exc:
            return f"probe failed: {exc}"
        exit_code = result.exit_code if hasattr(result, "exit_code") else 1
        if exit_code == 0:
            return None
        output = result.output.decode("utf-8", errors="replace") if isinstance(result.output, bytes) else str(result.output)
        return f"probe failed code={exit_code} output={output.strip()}"

    @staticmethod
    def _is_name_conflict(exc: APIError) -> bool:
        return ContainerLifecycle.is_name_conflict(exc)

    @staticmethod
    def _text_file_archive(path: str, content: str) -> tuple[str, bytes]:
        return text_file_archive(path, content)

    @staticmethod
    def _directory_archive(path: str, source: Path) -> tuple[str, bytes]:
        return directory_archive(path, source)
