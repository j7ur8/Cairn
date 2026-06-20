from __future__ import annotations

from typing import Any

from cairn.dispatcher.prompting import (
    load_prompt_from_execution_config,
    render_prompt,
)
from cairn.dispatcher.tasks.context import ContainerRuntime
from cairn.dispatcher.tasks.runner import PreparedTaskExecution
from cairn.dispatcher.tasks.task_snapshot import write_graph_snapshot_reference
from cairn.shared.config import DispatchConfig
from cairn.shared.contracts import Intent


def build_explore_execute_prompt(
    *,
    config: DispatchConfig,
    container_manager: ContainerRuntime,
    container_name: str,
    export_yaml: str,
    intent: Intent,
    prepared: PreparedTaskExecution,
    reporter: Any | None = None,
) -> str:
    return render_prompt(
        load_prompt_from_execution_config(
            prepared.execution_config,
            "explore.md",
            reporter,
        ),
        {
            "graph_yaml": write_graph_snapshot_reference(
                container_manager,
                container_name,
                export_yaml.strip(),
                phase="explore_execute",
            ),
            "intent_id": intent.id,
            "intent_description": intent.description,
            "capability_instructions": prepared.capabilities.instructions,
            "role_instructions": prepared.role.instructions,
        },
    )


def build_explore_conclude_prompt(
    *,
    config: DispatchConfig,
    container_manager: ContainerRuntime,
    container_name: str,
    export_yaml: str,
    intent: Intent,
    execution_config: dict | None = None,
    reporter: Any | None = None,
) -> str:
    return render_prompt(
        load_prompt_from_execution_config(
            execution_config,
            "explore_conclude.md",
            reporter,
        ),
        {
            "graph_yaml": write_graph_snapshot_reference(
                container_manager,
                container_name,
                export_yaml.strip(),
                phase="explore_conclude",
            ),
            "intent_id": intent.id,
            "intent_description": intent.description,
        },
    )
