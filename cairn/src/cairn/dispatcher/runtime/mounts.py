from __future__ import annotations

from pathlib import Path

from cairn.shared.config import ContainerConfig


def render_bind_mounts(config: ContainerConfig, project_id: str) -> list[dict[str, object]]:
    rendered: list[dict[str, object]] = []
    for index, mount in enumerate(config.bind_mounts):
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


def docker_volumes(config: ContainerConfig, project_id: str) -> dict[str, dict[str, str]]:
    volumes: dict[str, dict[str, str]] = {}
    for mount in render_bind_mounts(config, project_id):
        host_path = Path(str(mount["host_path"]))
        volumes[str(host_path)] = {
            "bind": str(mount["container_path"]),
            "mode": "ro" if mount["read_only"] else "rw",
        }
    return volumes
