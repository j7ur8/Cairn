from __future__ import annotations

from cairn.dispatcher.contracts import parse_json_output, validate_explore_payload
from cairn.dispatcher.tasks.context import TaskInvocation, TaskServices
from cairn.dispatcher.tasks.explore_prompt import build_explore_execute_prompt
from cairn.dispatcher.tasks.explore_result import run_explore_conclude_fallback
from cairn.dispatcher.tasks.intent_task import (
    IntentTaskContext,
    IntentTaskSpec,
    IntentWriteOutcome,
    run_intent_task,
)
from cairn.dispatcher.tasks.task_writeback import write_conclude_result_with_fact_id


def _build_prompt(ctx: IntentTaskContext) -> str:
    # explore always carries an export (run_explore_task requires str); the
    # shared context types it as optional because bootstrap leaves it None.
    assert ctx.export_yaml is not None
    return build_explore_execute_prompt(
        config=ctx.config,
        container_manager=ctx.container_manager,
        container_name=ctx.container_name,
        export_yaml=ctx.export_yaml,
        intent=ctx.intent,
        prepared=ctx.prepared,
    )


def _validate(model_output: str) -> tuple[str, object]:
    payload = parse_json_output(model_output)
    return validate_explore_payload(payload)


def _write_success(ctx: IntentTaskContext, payload) -> IntentWriteOutcome:
    description = payload
    conclude = write_conclude_result_with_fact_id(
        ctx.client,
        ctx.project.project.id,
        ctx.intent.id,
        ctx.worker.name,
        description,
        source="explore_execute",
        phase_ms=ctx.execute_ms,
        total_ms=ctx.total_ms,
    )
    return IntentWriteOutcome(
        outcome=conclude.status,
        fact_id=conclude.fact_id,
        result_phase="explore_write",
        result_description=description,
    )


def _conclude_fallback(ctx: IntentTaskContext) -> str:
    assert ctx.export_yaml is not None
    return run_explore_conclude_fallback(
        config=ctx.config,
        client=ctx.client,
        container_manager=ctx.container_manager,
        worker=ctx.worker,
        driver=ctx.driver,
        project_id=ctx.project.project.id,
        intent=ctx.intent,
        export_yaml=ctx.export_yaml,
        session=ctx.session,
        lease=ctx.lease,
        cancellation=ctx.cancellation,
        reporter=ctx.reporter,
        conclude_timeout=int(ctx.prepared.task_timeout["conclude_timeout"]),
        capability_context=ctx.prepared.capabilities.context,
    )


_EXPLORE_SPEC = IntentTaskSpec(
    task_type="explore",
    exec_phase="explore_execute",
    prepare_phase="explore_execute",
    capability_scope=lambda intent: f"explore-{intent.id}",
    build_prompt=_build_prompt,
    validate=_validate,
    write_success=_write_success,
    conclude_fallback=_conclude_fallback,
    emit_capability_manifest=None,
)


def run_explore_task(
    services: TaskServices,
    invocation: TaskInvocation,
) -> str:
    assert invocation.intent is not None
    assert invocation.export_yaml is not None
    return run_intent_task(
        _EXPLORE_SPEC,
        services,
        invocation,
    )
