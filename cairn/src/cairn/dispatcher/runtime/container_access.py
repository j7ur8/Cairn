from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from docker.models.containers import Container


class DockerAccess:
    def __init__(self, client: Any, *, docker_exception_type: type[Exception], not_found_type: type[Exception]) -> None:
        self.client = client
        self.docker_exception_type = docker_exception_type
        self.not_found_type = not_found_type

    def get_container(self, name: str) -> Container | None:
        try:
            return self.client.containers.get(name)
        except self.not_found_type:
            return None
        except self.docker_exception_type as exc:
            raise RuntimeError(f"failed to get container {name}: {exc}") from exc

    def require_container(self, name: str) -> Container:
        container = self.get_container(name)
        if container is None:
            raise RuntimeError(f"container not found: {name}")
        return container
