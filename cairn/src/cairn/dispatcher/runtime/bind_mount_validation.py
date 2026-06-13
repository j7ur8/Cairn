from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from cairn.dispatcher.runtime.mounts import render_bind_mounts
from cairn.shared.config import ContainerConfig


def mount_mismatches(
    *,
    config: ContainerConfig,
    project_id: str,
    container: Any | None,
    docker_exception_type: type[Exception],
) -> list[str]:
    expected = render_bind_mounts(config, project_id)
    if not expected or container is None:
        return []
    try:
        container.reload()
    except docker_exception_type as exc:
        return [f"failed to inspect mounts: {exc}"]
    actual_by_destination = {
        str(mount.get("Destination")): mount
        for mount in container.attrs.get("Mounts", [])
        if mount.get("Destination")
    }
    mismatches: list[str] = []
    for mount in expected:
        actual = actual_by_destination.get(str(mount["container_path"]))
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


def validate_bind_mounts(
    *,
    config: ContainerConfig,
    project_id: str,
    probe: Callable[[str, bool], str | None],
) -> list[str]:
    errors: list[str] = []
    for mount in render_bind_mounts(config, project_id):
        result = probe(str(mount["container_path"]), bool(mount["read_only"]))
        if result:
            errors.append(f"{mount['name']} {result}")
    return errors
