from __future__ import annotations

from cairn.dispatcher.contracts import parse_json_output, validate_bootstrap_execute_payload
from cairn.dispatcher.prompting import format_remote_support_instructions, load_prompt, render_prompt
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.tasks.bootstrap_prompt import bootstrap_prompt_replacements
from cairn.dispatcher.tasks.bootstrap_result import run_bootstrap_conclude_fallback, write_bootstrap_complete_result
from cairn.dispatcher.tasks.intent_task import (
    IntentTaskContext,
    IntentTaskSpec,
    IntentWriteOutcome,
    run_intent_task,
)
from cairn.shared.capability_projection import capability_manifest_payload, project_capability_data
from cairn.shared.config import DispatchConfig, WorkerConfig
from cairn.shared.contracts import Intent, ProjectDetail


def _emit_capability_manifest(reporter, project: ProjectDetail, execution_config: dict) -> None:
    reporter.emit_capability_manifest(
        "bootstrap_start",
        capability_manifest_payload(project.project.id, "bootstrap", project_capability_data(execution_config)),
    )


def _build_prompt(ctx: IntentTaskContext) -> str:
    prepared = ctx.prepared
    return render_prompt(
        load_prompt(ctx.config.runtime.prompt_group, "bootstrap.md"),
        {
            **bootstrap_prompt_replacements(ctx.project),
            "remote_support_instructions": format_remote_support_instructions(ctx.config.remote_support),
            "capability_instructions": prepared.capabilities.instructions,
            "role_instructions": prepared.role.instructions,
        },
    )


def _validate(model_output: str) -> tuple[str, object]:
    payload = parse_json_output(model_output)
    return validate_bootstrap_execute_payload(payload)


def _write_success(ctx: IntentTaskContext, payload) -> IntentWriteOutcome:
    data = payload
    complete = write_bootstrap_complete_result(
        ctx.client,
        ctx.project.project.id,
        ctx.intent.id,
        ctx.worker.name,
        data["fact_description"],
        data["complete_description"],
        source="bootstrap",
        phase_ms=ctx.execute_ms,
        total_ms=ctx.total_ms,
    )
    return IntentWriteOutcome(
        outcome=complete.status,
        fact_id=complete.fact_id,
        result_phase="bootstrap_write",
        result_description=data["complete_description"],
    )


def _conclude_fallback(ctx: IntentTaskContext) -> str:
    return run_bootstrap_conclude_fallback(
        config=ctx.config,
        client=ctx.client,
        container_manager=ctx.container_manager,
        worker=ctx.worker,
        driver=ctx.driver,
        project=ctx.project,
        intent=ctx.intent,
        session=ctx.session,
        lease=ctx.lease,
        cancellation=ctx.cancellation,
        reporter=ctx.reporter,
        conclude_timeout=int(ctx.prepared.task_timeout["conclude_timeout"]),
        capability_context=ctx.prepared.capabilities.context,
    )


_BOOTSTRAP_SPEC = IntentTaskSpec(
    task_type="bootstrap",
    exec_phase="bootstrap",
    prepare_phase="bootstrap_start",
    capability_scope=lambda intent: f"bootstrap-{intent.id}",
    build_prompt=_build_prompt,
    validate=_validate,
    write_success=_write_success,
    conclude_fallback=_conclude_fallback,
    emit_capability_manifest=_emit_capability_manifest,
)


def run_bootstrap_task(
    config: DispatchConfig,
    client: CairnClient,
    container_manager: ContainerManager,
    project: ProjectDetail,
    intent: Intent,
    worker: WorkerConfig,
    execution_config: dict,
    cancellation: TaskCancellation,
) -> str:
    return run_intent_task(
        _BOOTSTRAP_SPEC,
        config,
        client,
        container_manager,
        project,
        intent,
        worker,
        execution_config,
        cancellation,
    )
