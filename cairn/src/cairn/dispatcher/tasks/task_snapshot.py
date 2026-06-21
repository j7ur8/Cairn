from __future__ import annotations

import uuid

from cairn.dispatcher.tasks.context import ContainerRuntime
from cairn.dispatcher.tasks.task_text import GRAPH_SNAPSHOT_ROOT


def write_task_snapshot_reference(
    container_manager: ContainerRuntime,
    container_name: str,
    content: str,
    *,
    filename: str,
    phase: str,
) -> str:
    path = f"{GRAPH_SNAPSHOT_ROOT}/{phase}-{uuid.uuid4().hex[:12]}/{filename}"
    container_manager.write_text_file(container_name, path, content)
    return (
        f"The {filename} snapshot is stored in this file inside the current container:\n\n"
        f"{path}\n\n"
        f"Before using this snapshot, read the entire file and treat its contents as {filename} "
        "for this task."
    )


def write_graph_snapshot_reference(
    container_manager: ContainerRuntime,
    container_name: str,
    graph_yaml: str,
    *,
    phase: str,
) -> str:
    return write_task_snapshot_reference(
        container_manager,
        container_name,
        graph_yaml,
        filename="graph.yaml",
        phase=phase,
    )
