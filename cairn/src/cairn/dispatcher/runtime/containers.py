from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from pathlib import PurePosixPath
import tarfile
import threading
import uuid
from typing import Callable

import docker
from docker.errors import APIError, DockerException, NotFound
from docker.models.containers import Container

from cairn.dispatcher.config import ContainerConfig
from cairn.dispatcher.runtime.process import ManagedProcess

LOG = logging.getLogger(__name__)


class ContainerManager:
    _PREFIX = "cairn-dispatch-"
    _STARTUP_PREFIX = "cairn-startup-healthcheck-"
    _STARTUP_PROJECT_ID = "startup-healthcheck"

    def __init__(
        self,
        config: ContainerConfig,
        bearer_token_env_keys: tuple[str, ...] = (),
        proxy_resolver: Callable[[str], dict[str, str] | None] | None = None,
    ):
        self._config = config
        self._bearer_token_env_keys = tuple(dict.fromkeys(bearer_token_env_keys))  # dedupe, keep order
        self._proxy_resolver = proxy_resolver
        self._client = docker.from_env()
        self._ensure_running_locks: dict[str, threading.Lock] = {}
        self._ensure_running_locks_guard = threading.Lock()
        self._logged_mount_mismatches: set[tuple[str, str]] = set()

    def _bearer_token_environment(self) -> dict[str, str]:
        """Resolve bearer-token env var references to actual values from the
        dispatcher's ``os.environ``. Only includes vars that are set, so a
        missing var (which would have failed ``DispatchConfig.load()`` anyway)
        is silently dropped here.
        """
        env: dict[str, str] = {}
        for name in self._bearer_token_env_keys:
            value = os.environ.get(name)
            if value is not None:
                env[name] = value
        return env

    def _proxy_environment(self, project_id: str) -> dict[str, str]:
        """Resolve the per-project proxy at container-launch time.

        Returns an empty dict when no proxy is configured. The resolver is a
        callable (not a value) so each container start picks up the latest
        proxy config from the Server without a long-lived cache in
        ``ContainerManager``.
        """
        if self._proxy_resolver is None:
            return {}
        resolved = self._proxy_resolver(project_id) or {}
        return dict(resolved)

    def close(self) -> None:
        self._client.close()

    def container_name(self, project_id: str) -> str:
        sanitized = project_id.replace("/", "-")
        return f"{self._PREFIX}{sanitized}"

    def ensure_running(self, project_id: str) -> str:
        name = self.container_name(project_id)
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
            self._start_existing(name)
            return name
        LOG.info("creating container project=%s container=%s image=%s", project_id, name, self._config.image)
        try:
            volumes = self._docker_volumes(project_id)
            env = self._bearer_token_environment() or None
            self._client.containers.run(
                self._config.image,
                ["sleep", "infinity"],
                detach=True,
                name=name,
                network_mode=self._config.network_mode,
                cap_add=self._config.cap_add or None,
                volumes=volumes or None,
                environment={**(env or {}), **self._proxy_environment(project_id)} or None,
                user=self._config.user,
            )
            LOG.info("created container project=%s container=%s", project_id, name)
            return name
        except APIError as exc:
            if not self._is_name_conflict(exc):
                raise RuntimeError(f"failed to create container {name}: {exc}") from exc
        LOG.info("container name conflict, reusing existing container project=%s container=%s", project_id, name)
        state = self.inspect_state(name)
        if state == "running":
            self.log_mount_mismatches(name, project_id)
            return name
        if state is not None:
            self.log_mount_mismatches(name, project_id)
            LOG.info("starting conflicted existing container project=%s container=%s state=%s", project_id, name, state)
            self._start_existing(name)
            return name
        raise RuntimeError(f"failed to create container {name}")

    def _ensure_running_lock(self, name: str) -> threading.Lock:
        with self._ensure_running_locks_guard:
            lock = self._ensure_running_locks.get(name)
            if lock is None:
                lock = threading.Lock()
                self._ensure_running_locks[name] = lock
            return lock

    def create_startup_container(self) -> str:
        name = f"{self._STARTUP_PREFIX}{uuid.uuid4().hex[:12]}"
        LOG.debug("creating startup healthcheck container container=%s image=%s", name, self._config.image)
        try:
            volumes = self._docker_volumes(self._STARTUP_PROJECT_ID)
            env = self._bearer_token_environment() or None
            self._client.containers.run(
                self._config.image,
                ["sleep", "infinity"],
                detach=True,
                name=name,
                network_mode=self._config.network_mode,
                cap_add=self._config.cap_add or None,
                volumes=volumes or None,
                environment={**(env or {}), **self._proxy_environment(self._STARTUP_PROJECT_ID)} or None,
                user=self._config.user,
            )
        except DockerException as exc:
            raise RuntimeError(f"failed to create startup container {name}: {exc}") from exc
        return name

    def validate_bind_mounts(self, container_name: str, project_id: str) -> list[str]:
        errors: list[str] = []
        for mount in self._render_bind_mounts(project_id):
            host_path = Path(mount["host_path"])
            if not host_path.exists():
                errors.append(f"{mount['name']} host path does not exist: {host_path}")
                continue
            if not host_path.is_dir():
                errors.append(f"{mount['name']} host path is not a directory: {host_path}")
                continue
            if not mount["read_only"] and not self._host_dir_writable(host_path):
                errors.append(f"{mount['name']} host path is not writable: {host_path}")
                continue
            probe = self._probe_bind_mount(container_name, mount["container_path"], mount["read_only"])
            if probe:
                errors.append(f"{mount['name']} {probe}")
        return errors

    def log_managed_container_mount_mismatches(self) -> None:
        for name in self.managed_container_names():
            project_id = name.removeprefix(self._PREFIX)
            self.log_mount_mismatches(name, project_id)

    def log_mount_mismatches(self, container_name: str, project_id: str) -> None:
        mismatches = self.mount_mismatches(container_name, project_id)
        for mismatch in mismatches:
            log_key = (container_name, mismatch)
            if log_key in self._logged_mount_mismatches:
                continue
            self._logged_mount_mismatches.add(log_key)
            LOG.warning("container bind mount mismatch container=%s project=%s %s", container_name, project_id, mismatch)

    def mount_mismatches(self, container_name: str, project_id: str) -> list[str]:
        expected = self._render_bind_mounts(project_id)
        if not expected:
            return []
        container = self._get_container(container_name)
        if container is None:
            return []
        try:
            container.reload()
        except DockerException as exc:
            return [f"failed to inspect mounts: {exc}"]
        actual_by_destination = {
            str(mount.get("Destination")): mount
            for mount in container.attrs.get("Mounts", [])
            if mount.get("Destination")
        }
        mismatches: list[str] = []
        for mount in expected:
            actual = actual_by_destination.get(mount["container_path"])
            if actual is None:
                mismatches.append(f"missing {mount['name']} at {mount['container_path']}")
                continue
            actual_source = str(Path(str(actual.get("Source", ""))).resolve(strict=False))
            if actual_source != mount["host_path"]:
                mismatches.append(
                    f"{mount['name']} source mismatch expected={mount['host_path']} actual={actual_source}"
                )
            actual_rw = bool(actual.get("RW"))
            expected_rw = not mount["read_only"]
            if actual_rw != expected_rw:
                mismatches.append(
                    f"{mount['name']} mode mismatch expected={'rw' if expected_rw else 'ro'} actual={'rw' if actual_rw else 'ro'}"
                )
        return mismatches

    def inspect_state(self, name: str) -> str | None:
        container = self._get_container(name)
        if container is None:
            return None
        try:
            container.reload()
        except DockerException as exc:
            raise RuntimeError(f"failed to inspect container {name}: {exc}") from exc
        state = container.attrs.get("State", {}).get("Status")
        return str(state) if state else None

    def cleanup_completed(self, project_id: str) -> bool:
        name = self.container_name(project_id)
        state = self.inspect_state(name)
        if state is None:
            return True
        container = self._require_container(name)
        if self._config.completed_action == "remove":
            LOG.info("removing completed project container project=%s container=%s", project_id, name)
            try:
                container.remove(force=True)
            except NotFound:
                return True
            except DockerException as exc:
                LOG.warning("failed to remove container=%s error=%s", name, exc)
                return False
            return self.inspect_state(name) is None
        elif state == "running":
            LOG.info("stopping completed project container project=%s container=%s", project_id, name)
            try:
                container.stop(timeout=1)
            except NotFound:
                return True
            except DockerException as exc:
                LOG.warning("failed to stop container=%s error=%s", name, exc)
                return False
            return self.inspect_state(name) != "running"
        return True

    def cleanup_stopped(self, project_id: str) -> bool:
        name = self.container_name(project_id)
        state = self.inspect_state(name)
        if state is None:
            return True
        container = self._require_container(name)
        if self._config.stopped_action == "remove":
            LOG.info("removing stopped project container project=%s container=%s", project_id, name)
            try:
                container.remove(force=True)
            except NotFound:
                return True
            except DockerException as exc:
                LOG.warning("failed to remove stopped project container=%s error=%s", name, exc)
                return False
            return self.inspect_state(name) is None

        if state != "running":
            return True
        LOG.info("stopping stopped project container project=%s container=%s", project_id, name)
        try:
            container.stop(timeout=1)
        except NotFound:
            return True
        except DockerException as exc:
            LOG.warning("failed to stop stopped project container=%s error=%s", name, exc)
            return False
        return self.inspect_state(name) != "running"

    def cleanup_orphan(self, name: str) -> bool:
        state = self.inspect_state(name)
        if state is None:
            return True
        LOG.info("removing orphan project container container=%s state=%s", name, state)
        container = self._require_container(name)
        try:
            container.remove(force=True)
        except NotFound:
            return True
        except DockerException as exc:
            LOG.warning("failed to remove orphan container=%s error=%s", name, exc)
            return False
        return self.inspect_state(name) is None

    def managed_container_names(self) -> list[str]:
        try:
            containers = self._client.containers.list(all=True)
        except DockerException as exc:
            LOG.warning("failed to list managed containers error=%s", exc)
            return []
        return sorted(container.name for container in containers if container.name.startswith(self._PREFIX))

    def needs_completed_cleanup(self, project_id: str) -> bool:
        name = self.container_name(project_id)
        state = self.inspect_state(name)
        if state is None:
            return False
        if self._config.completed_action == "remove":
            return True
        return state == "running"

    def needs_orphan_cleanup(self, name: str) -> bool:
        return self.inspect_state(name) is not None

    def needs_stopped_cleanup(self, project_id: str) -> bool:
        state = self.inspect_state(self.container_name(project_id))
        if state is None:
            return False
        if self._config.stopped_action == "remove":
            return True
        return state == "running"

    def build_exec_process(
        self,
        container_name: str,
        env: dict[str, str],
        command: list[str],
        timeout_seconds: int | None = None,
        kill_after_seconds: int = 5,
        on_output: Callable[[str, str], None] | None = None,
    ) -> ManagedProcess:
        container = self._require_container(container_name)
        argv: list[str] = []
        if timeout_seconds is not None:
            argv.extend(
                [
                    "timeout",
                    "-k",
                    f"{kill_after_seconds}s",
                    f"{timeout_seconds}s",
                ]
            )
        argv.extend(command)
        return ManagedProcess(container, argv, env, user=self._config.exec_user, on_output=on_output)

    def write_text_file(self, container_name: str, path: str, content: str) -> None:
        archive_path, archive = self._text_file_archive(path, content)
        container = self._require_container(container_name)
        try:
            ok = container.put_archive(archive_path, archive)
        except DockerException as exc:
            raise RuntimeError(f"failed to write container file {path}: {exc}") from exc
        if not ok:
            raise RuntimeError(f"failed to write container file {path}")

    def write_directory(self, container_name: str, path: str, source: Path) -> None:
        archive_path, archive = self._directory_archive(path, source)
        container = self._require_container(container_name)
        try:
            ok = container.put_archive(archive_path, archive)
        except DockerException as exc:
            raise RuntimeError(f"failed to write container directory {path}: {exc}") from exc
        if not ok:
            raise RuntimeError(f"failed to write container directory {path}")

    def remove_container(self, name: str, *, force: bool = True) -> None:
        container = self._get_container(name)
        if container is None:
            return
        try:
            container.remove(force=force)
        except NotFound:
            return
        except DockerException as exc:
            LOG.warning("failed to remove container=%s error=%s", name, exc)

    def _start_existing(self, name: str) -> None:
        LOG.debug("starting container=%s", name)
        container = self._require_container(name)
        try:
            container.start()
            return
        except DockerException as exc:
            if self.inspect_state(name) == "running":
                return
            raise RuntimeError(f"failed to start container {name}: {exc}") from exc

    def _get_container(self, name: str) -> Container | None:
        try:
            return self._client.containers.get(name)
        except NotFound:
            return None
        except DockerException as exc:
            raise RuntimeError(f"failed to get container {name}: {exc}") from exc

    def _require_container(self, name: str) -> Container:
        container = self._get_container(name)
        if container is None:
            raise RuntimeError(f"container not found: {name}")
        return container

    def _docker_volumes(self, project_id: str) -> dict[str, dict[str, str]]:
        volumes: dict[str, dict[str, str]] = {}
        for mount in self._render_bind_mounts(project_id):
            host_path = Path(mount["host_path"])
            host_path.mkdir(parents=True, exist_ok=True)
            if not host_path.is_dir():
                raise RuntimeError(f"bind mount host path is not a directory: {host_path}")
            if not mount["read_only"]:
                _ensure_world_writable_dir(host_path)
            volumes[str(host_path)] = {
                "bind": mount["container_path"],
                "mode": "ro" if mount["read_only"] else "rw",
            }
        return volumes

    def _render_bind_mounts(self, project_id: str) -> list[dict[str, object]]:
        rendered: list[dict[str, object]] = []
        for index, mount in enumerate(self._config.bind_mounts):
            name = mount.name or f"bind_mount[{index}]"
            host_path = mount.host_path.replace("{project_id}", project_id)
            rendered.append(
                {
                    "name": name,
                    "host_path": str(Path(host_path).expanduser().resolve(strict=False)),
                    "container_path": mount.container_path,
                    "read_only": mount.read_only,
                }
            )
        return rendered

    @staticmethod
    def _host_dir_writable(path: Path) -> bool:
        probe = path / f".cairn-write-test-{uuid.uuid4().hex[:12]}"
        try:
            probe.write_text("ok", encoding="utf-8")
        except OSError:
            return False
        try:
            probe.unlink()
        except OSError:
            LOG.debug("failed to remove host bind mount write probe path=%s", probe)
        return True

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
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        explanation = str(getattr(exc, "explanation", "") or exc)
        return status_code == 409 or "is already in use" in explanation

    @staticmethod
    def _text_file_archive(path: str, content: str) -> tuple[str, bytes]:
        target = PurePosixPath(path)
        if not target.is_absolute() or target.name in ("", ".", ".."):
            raise ValueError(f"container file path must be absolute: {path}")
        parts = target.parts[1:]
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise ValueError(f"invalid container file path: {path}")
        if len(parts) == 1:
            archive_path = "/"
            archive_parts = parts
        else:
            archive_path = f"/{parts[0]}"
            archive_parts = parts[1:]

        payload = content.encode("utf-8")
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            parent = ""
            for part in archive_parts[:-1]:
                parent = f"{parent}/{part}" if parent else part
                info = tarfile.TarInfo(parent)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                archive.addfile(info)

            file_name = "/".join(archive_parts)
            info = tarfile.TarInfo(file_name)
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))
        return archive_path, stream.getvalue()

    @staticmethod
    def _directory_archive(path: str, source: Path) -> tuple[str, bytes]:
        target = PurePosixPath(path)
        if not target.is_absolute() or target.name in ("", ".", ".."):
            raise ValueError(f"container directory path must be absolute: {path}")
        parts = target.parts[1:]
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise ValueError(f"invalid container directory path: {path}")
        source = source.resolve(strict=True)
        if not source.is_dir():
            raise ValueError(f"source must be a directory: {source}")
        archive_path = f"/{parts[0]}" if len(parts) > 1 else "/"
        prefix = "/".join(parts[1:]) if len(parts) > 1 else parts[0]

        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            root_info = tarfile.TarInfo(prefix)
            root_info.type = tarfile.DIRTYPE
            root_info.mode = 0o755
            archive.addfile(root_info)
            for item in sorted(source.rglob("*")):
                relative = item.relative_to(source)
                if any(part in ("", ".", "..") for part in relative.parts):
                    continue
                arcname = f"{prefix}/{relative}"
                if item.is_dir():
                    info = tarfile.TarInfo(arcname)
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    archive.addfile(info)
                elif item.is_file():
                    archive.add(item, arcname=arcname, recursive=False)
        return archive_path, stream.getvalue()


def _ensure_world_writable_dir(path: Path) -> None:
    """Best-effort: make the host bind-mount dir world-writable.

    If the dispatcher's process does not own ``path`` (e.g. it is running as a
    non-root user inside the ``cairn-dispatcher`` container while the file is
    owned by the host user), ``os.chmod`` raises ``PermissionError``. The
    probe inside the worker container is the real source of truth for write
    permission, so we downgrade the chmod failure to a warning rather than
    crashing container creation.
    """
    mode = path.stat().st_mode
    if mode & 0o002:
        return
    try:
        os.chmod(path, mode | 0o777)
    except PermissionError as exc:
        LOG.warning(
            "skipping chmod 0o777 on host bind mount (dispatcher lacks owner privilege); "
            "operator should ensure the path is world-writable. path=%s err=%s",
            path,
            exc,
        )
