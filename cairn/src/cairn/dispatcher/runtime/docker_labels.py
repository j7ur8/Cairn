from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docker.models.containers import Container

CONTAINER_PREFIX = "cairn-worker-"
STARTUP_CONTAINER_NAME = "cairn-worker-startup-healthcheck"
STARTUP_PROJECT_ID = "startup-healthcheck"
LABEL_MANAGED = "cairn.managed"
LABEL_PROJECT_ID = "cairn.project_id"
LABEL_STARTUP = "cairn.startup_healthcheck"


def container_name(project_id: str) -> str:
    sanitized = project_id.replace("/", "-")
    return f"{CONTAINER_PREFIX}{sanitized}"


def container_labels(project_id: str, *, startup: bool = False) -> dict[str, str]:
    return {
        LABEL_MANAGED: "true",
        LABEL_PROJECT_ID: project_id,
        LABEL_STARTUP: "true" if startup else "false",
    }


def is_startup_container(container: Container) -> bool:
    if container.name == STARTUP_CONTAINER_NAME:
        return True
    labels = getattr(container, "labels", None)
    if isinstance(labels, dict) and labels.get(LABEL_STARTUP) == "true":
        return True
    return False
