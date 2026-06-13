from __future__ import annotations

import logging

from cairn.dispatcher.prompting import format_fact_ids, format_open_intents, load_prompt, render_prompt
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.tasks.runner import PreparedTaskExecution
from cairn.dispatcher.tasks.task_snapshot import write_graph_snapshot_reference
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
    container_manager: ContainerManager,
    container_name: str,
    project: ProjectDetail,
    export_yaml: str,
    prepared: PreparedTaskExecution,
    worker: WorkerConfig,
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
    prompt = render_prompt(
        load_prompt(config.runtime.prompt_group, "reason.md"),
        {
            "graph_yaml": write_graph_snapshot_reference(
                container_manager,
                container_name,
                export_yaml.strip(),
                phase="reason_execute",
            ),
            "fact_ids": format_fact_ids(allowed_fact_ids),
            "open_intents": format_open_intents(open_intents),
            "max_intents": str(config.tasks.reason.max_intents),
            "capability_instructions": prepared.capabilities.instructions,
            "role_instructions": prepared.role.instructions,
        },
    )
    return prompt, open_intents, allowed_fact_ids
