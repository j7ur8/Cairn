from __future__ import annotations

from typing import Any

from cairn.dispatcher.prompting import (
    load_prompt_from_execution_config,
    render_prompt,
)
from cairn.dispatcher.tasks.bootstrap_prompt import bootstrap_prompt_replacements
from cairn.dispatcher.tasks.context import ContainerRuntime
from cairn.dispatcher.tasks.fact_views import FactViewRenderer
from cairn.dispatcher.tasks.runner import PreparedTaskExecution
from cairn.dispatcher.tasks.task_snapshot import write_graph_snapshot_reference, write_task_snapshot_reference
from cairn.shared.config import DispatchConfig
from cairn.shared.contracts import Intent, ProjectDetail


def build_explore_execute_prompt(
    *,
    config: DispatchConfig,
    container_manager: ContainerRuntime,
    container_name: str,
    export_yaml: str,
    project: ProjectDetail,
    intent: Intent,
    prepared: PreparedTaskExecution,
    reporter: Any | None = None,
) -> str:
    full_graph_reference = write_graph_snapshot_reference(
        container_manager,
        container_name,
        export_yaml.strip(),
        phase="explore_execute",
    )
    fact_view = FactViewRenderer().render_worker_view(
        project,
        intent=intent,
        full_graph_reference=full_graph_reference,
    )
    fact_view_reference = write_task_snapshot_reference(
        container_manager,
        container_name,
        fact_view.yaml_text.strip(),
        filename="worker-view.yaml",
        phase="explore_execute",
    )
    return render_prompt(
        load_prompt_from_execution_config(
            prepared.execution_config,
            "explore.md",
            reporter,
        ),
        {
            "hints": bootstrap_prompt_replacements(project)["hints"],
            "fact_view": fact_view_reference,
            "full_graph": full_graph_reference,
            "graph_yaml": full_graph_reference,
            "intent_id": intent.id,
            "intent_description": intent.description,
        },
    )


def build_explore_conclude_prompt(
    *,
    config: DispatchConfig,
    container_manager: ContainerRuntime,
    container_name: str,
    export_yaml: str,
    project: ProjectDetail,
    intent: Intent,
    execution_config: dict | None = None,
    reporter: Any | None = None,
) -> str:
    full_graph_reference = write_graph_snapshot_reference(
        container_manager,
        container_name,
        export_yaml.strip(),
        phase="explore_conclude",
    )
    fact_view = FactViewRenderer().render_conclude_view(
        project,
        intent=intent,
        full_graph_reference=full_graph_reference,
    )
    fact_view_reference = write_task_snapshot_reference(
        container_manager,
        container_name,
        fact_view.yaml_text.strip(),
        filename="conclude-view.yaml",
        phase="explore_conclude",
    )
    return render_prompt(
        load_prompt_from_execution_config(
            execution_config,
            "explore_conclude.md",
            reporter,
        ),
        {
            "hints": bootstrap_prompt_replacements(project)["hints"],
            "fact_view": fact_view_reference,
            "full_graph": full_graph_reference,
            "graph_yaml": full_graph_reference,
            "intent_id": intent.id,
            "intent_description": intent.description,
        },
    )
