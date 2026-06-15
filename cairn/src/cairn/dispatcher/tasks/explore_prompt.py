from __future__ import annotations

from cairn.dispatcher.prompting import format_remote_support_instructions, load_prompt, render_prompt
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
) -> str:
    return render_prompt(
        load_prompt(config.runtime.prompt_group, "explore.md"),
        {
            "graph_yaml": write_graph_snapshot_reference(
                container_manager,
                container_name,
                export_yaml.strip(),
                phase="explore_execute",
            ),
            "intent_id": intent.id,
            "intent_description": intent.description,
            "remote_support_instructions": format_remote_support_instructions(config.remote_support),
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
) -> str:
    return render_prompt(
        load_prompt(config.runtime.prompt_group, "explore_conclude.md"),
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
