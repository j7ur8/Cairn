from __future__ import annotations

from pathlib import Path

from cairn.dispatcher.runtime.archive_writer import directory_archive, text_file_archive
from cairn.dispatcher.runtime.container_access import DockerAccess


class ContainerFiles:
    def __init__(self, *, access: DockerAccess, docker_exception_type: type[Exception]) -> None:
        self.access = access
        self.docker_exception_type = docker_exception_type

    def write_text_file(self, container_name: str, path: str, content: str) -> None:
        archive_path, archive = text_file_archive(path, content)
        self._put_archive(container_name, archive_path, archive, f"failed to write container file {path}")

    def write_directory(self, container_name: str, path: str, source: Path) -> None:
        archive_path, archive = directory_archive(path, source)
        self._put_archive(container_name, archive_path, archive, f"failed to write container directory {path}")

    def _put_archive(self, container_name: str, archive_path: str, archive: bytes, message: str) -> None:
        container = self.access.require_container(container_name)
        try:
            ok = container.put_archive(archive_path, archive)
        except self.docker_exception_type as exc:
            raise RuntimeError(f"{message}: {exc}") from exc
        if not ok:
            raise RuntimeError(message)
