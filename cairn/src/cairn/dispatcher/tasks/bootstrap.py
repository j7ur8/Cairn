from __future__ import annotations

from cairn.dispatcher.contracts import parse_sentinel_fact_output
from cairn.dispatcher.prompting import (
    load_prompt_from_execution_config,
    render_prompt,
)
from cairn.dispatcher.tasks.bootstrap_prompt import bootstrap_prompt_replacements
from cairn.dispatcher.tasks.bootstrap_result import run_bootstrap_conclude_fallback
from cairn.dispatcher.tasks.context import TaskInvocation, TaskServices
from cairn.dispatcher.tasks.intent_task import (
    IntentTaskContext,
    IntentTaskSpec,
    IntentWriteOutcome,
    run_intent_task,
)
from cairn.dispatcher.tasks.task_writeback import write_conclude_result_with_fact_id
from cairn.shared.capability_projection import capability_manifest_payload, project_capability_data
from cairn.shared.contracts import ProjectDetail


def _emit_capability_manifest(reporter, project: ProjectDetail, execution_config: dict) -> None:
    reporter.emit_capability_manifest(
        "bootstrap_start",
        capability_manifest_payload(project.project.id, "bootstrap", project_capability_data(execution_config)),
    )


def _build_prompt(ctx: IntentTaskContext) -> str:
    prepared = ctx.prepared
    return render_prompt(
        load_prompt_from_execution_config(
            prepared.execution_config,
            "bootstrap.md",
            ctx.reporter,
        ),
        {
            **bootstrap_prompt_replacements(ctx.project),
        },
    )


def _validate(model_output: str) -> tuple[str, object]:
    return "fact", parse_sentinel_fact_output(model_output)


def _write_success(ctx: IntentTaskContext, payload) -> IntentWriteOutcome:
    fact_description = payload
    conclude = write_conclude_result_with_fact_id(
        ctx.client,
        ctx.project.project.id,
        ctx.intent.id,
        ctx.worker.name,
        fact_description,
        source="bootstrap",
        phase_ms=ctx.execute_ms,
        total_ms=ctx.total_ms,
    )
    return IntentWriteOutcome(
        outcome=conclude.status,
        fact_id=conclude.fact_id,
        result_phase="bootstrap_write",
        result_description=fact_description,
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
        execution_config=ctx.prepared.execution_config,
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
    services: TaskServices,
    invocation: TaskInvocation,
) -> str:
    assert invocation.intent is not None
    return run_intent_task(
        _BOOTSTRAP_SPEC,
        services,
        invocation,
    )
