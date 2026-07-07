from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docker.models.containers import Container

CONTAINER_PREFIX = "cairn-worker-"
RUNNER_CONTAINER_PREFIX = "cairn-runner-"
STARTUP_CONTAINER_NAME = "cairn-worker-startup-healthcheck"
STARTUP_PROJECT_ID = "startup-healthcheck"
LABEL_MANAGED = "cairn.managed"
LABEL_PROJECT_ID = "cairn.project_id"
LABEL_STARTUP = "cairn.startup_healthcheck"
LABEL_KIND = "cairn.kind"
LABEL_TASK_ID = "cairn.task_id"
LABEL_PHASE = "cairn.phase"


def safe_project_id(project_id: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", project_id.strip())
    text = text.strip(".-")
    return text or "unknown"


def container_name(project_id: str) -> str:
    return f"{CONTAINER_PREFIX}{safe_project_id(project_id)}"


def runner_container_name(project_id: str, task_id: str) -> str:
    return f"{RUNNER_CONTAINER_PREFIX}{safe_project_id(project_id)}-{safe_project_id(task_id)}"


def container_labels(
    project_id: str,
    *,
    startup: bool = False,
    kind: str = "worker",
    task_id: str | None = None,
    phase: str | None = None,
) -> dict[str, str]:
    labels = {
        LABEL_MANAGED: "true",
        LABEL_PROJECT_ID: project_id,
        LABEL_STARTUP: "true" if startup else "false",
        LABEL_KIND: kind,
    }
    if task_id:
        labels[LABEL_TASK_ID] = task_id
    if phase:
        labels[LABEL_PHASE] = phase
    return labels


def is_startup_container(container: Container) -> bool:
    if container.name == STARTUP_CONTAINER_NAME:
        return True
    labels = getattr(container, "labels", None)
    if isinstance(labels, dict) and labels.get(LABEL_STARTUP) == "true":
        return True
    return False
