from __future__ import annotations

import logging
from typing import Any

from cairn.dispatcher.prompting import (
    format_fact_ids,
    format_open_intents,
    load_prompt_from_execution_config,
    render_prompt,
)
from cairn.dispatcher.tasks.bootstrap_prompt import bootstrap_prompt_replacements
from cairn.dispatcher.tasks.context import ContainerRuntime
from cairn.dispatcher.tasks.fact_views import FactViewRenderer
from cairn.dispatcher.tasks.runner import PreparedTaskExecution
from cairn.dispatcher.tasks.task_snapshot import write_graph_snapshot_reference, write_task_snapshot_reference
from cairn.shared.config import DispatchConfig, WorkerConfig
from cairn.shared.contracts import ProjectDetail

LOG = logging.getLogger(__name__)


def reason_open_intents(project: ProjectDetail) -> list[dict[str, object]]:
    return [
        {
            "id": intent.id,
            "from": intent.from_,
            "description": intent.description,
            "worker": intent.worker,
        }
        for intent in project.intents
        if intent.to is None
    ]


def reason_allowed_fact_ids(project: ProjectDetail) -> list[str]:
    return [fact.id for fact in project.facts if fact.id != "goal"]


def build_reason_execute_prompt(
    *,
    config: DispatchConfig,
    container_manager: ContainerRuntime,
    container_name: str,
    project: ProjectDetail,
    export_yaml: str,
    prepared: PreparedTaskExecution,
    worker: WorkerConfig,
    reporter: Any | None = None,
) -> tuple[str, list[dict[str, object]], list[str]]:
    open_intents = reason_open_intents(project)
    allowed_fact_ids = reason_allowed_fact_ids(project)
    LOG.debug(
        "reason context prepared project=%s worker=%s facts=%s allowed_fact_ids=%s hints=%s open_intents=%s",
        project.project.id,
        worker.name,
        len(project.facts),
        len(allowed_fact_ids),
        len(project.hints),
        len(open_intents),
    )
    full_graph_reference = write_graph_snapshot_reference(
        container_manager,
        container_name,
        export_yaml.strip(),
        phase="reason_execute",
    )
    fact_view = FactViewRenderer().render_reason_view(
        project,
        full_graph_reference=full_graph_reference,
    )
    fact_view_reference = write_task_snapshot_reference(
        container_manager,
        container_name,
        fact_view.yaml_text.strip(),
        filename="reason-view.yaml",
        phase="reason_execute",
    )
    prompt = render_prompt(
        load_prompt_from_execution_config(
            prepared.execution_config,
            "reason.md",
            reporter,
        ),
        {
            "hints": bootstrap_prompt_replacements(project)["hints"],
            "fact_view": fact_view_reference,
            "full_graph": full_graph_reference,
            "graph_yaml": full_graph_reference,
            "fact_ids": format_fact_ids(allowed_fact_ids),
            "open_intents": format_open_intents(open_intents),
            "max_intents": str(config.tasks.reason.max_intents),
        },
    )
    return prompt, open_intents, allowed_fact_ids
