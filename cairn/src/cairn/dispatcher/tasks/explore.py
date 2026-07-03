from __future__ import annotations

import logging

from cairn.dispatcher.contracts import parse_json_output, parse_sentinel_fact_output, validate_explore_payload
from cairn.dispatcher.tasks.context import TaskInvocation, TaskServices
from cairn.dispatcher.tasks.explore_prompt import build_explore_execute_prompt
from cairn.dispatcher.tasks.explore_result import run_explore_conclude_fallback
from cairn.dispatcher.tasks.healthcheck_gate import run_intent_healthcheck_gate
from cairn.dispatcher.tasks.intent_task import (
    IntentTaskContext,
    IntentTaskSpec,
    IntentWriteOutcome,
    run_intent_task,
)
from cairn.dispatcher.tasks.lifecycle import TaskLifecycle, TaskRunContext
from cairn.dispatcher.tasks.runner import project_task_timeout
from cairn.dispatcher.tasks.task_release import best_effort_release
from cairn.dispatcher.tasks.task_writeback import write_conclude_result_with_fact_id
from cairn.dispatcher.workers.registry import get_driver

LOG = logging.getLogger(__name__)


def _build_prompt(ctx: IntentTaskContext) -> str:
    # explore always carries an export (run_explore_task requires str); the
    # shared context types it as optional because bootstrap leaves it None.
    assert ctx.export_yaml is not None
    return build_explore_execute_prompt(
        config=ctx.config,
        container_manager=ctx.container_manager,
        container_name=ctx.container_name,
        export_yaml=ctx.export_yaml,
        project=ctx.project,
        intent=ctx.intent,
        prepared=ctx.prepared,
        reporter=ctx.reporter,
    )


def _validate(model_output: str) -> tuple[str, object]:
    try:
        return "fact", parse_sentinel_fact_output(model_output)
    except ValueError:
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
        project=ctx.project,
        project_id=ctx.project.project.id,
        intent=ctx.intent,
        export_yaml=ctx.export_yaml,
        session=ctx.session,
        lease=ctx.lease,
        cancellation=ctx.cancellation,
        reporter=ctx.reporter,
        conclude_timeout=int(ctx.prepared.task_timeout["conclude_timeout"]),
        capability_context=ctx.prepared.capabilities.context,
        execution_config=ctx.prepared.execution_config,
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
    if invocation.checkpoint_session_id:
        return _run_explore_conclude_only_task(services, invocation)
    return run_intent_task(
        _EXPLORE_SPEC,
        services,
        invocation,
    )


def _run_explore_conclude_only_task(
    services: TaskServices,
    invocation: TaskInvocation,
) -> str:
    config = services.config
    client = services.client
    container_manager = services.container_runtime
    project = invocation.project
    intent = invocation.intent
    assert intent is not None
    export_yaml = invocation.export_yaml
    assert export_yaml is not None
    session_id = invocation.checkpoint_session_id
    assert session_id is not None
    worker = invocation.worker
    project_id = project.project.id
    cancellation = invocation.cancellation
    if cancellation.reason is not None:
        best_effort_release(client, project_id, intent.id, worker.name)
        return "cancelled"

    driver = get_driver(worker.type)
    lifecycle = TaskLifecycle(
        TaskRunContext(
            config=config,
            client=client,
            project_id=project_id,
            task_type="explore",
            worker=worker,
            intent_id=intent.id,
        )
    )
    reporter = lifecycle.reporter
    lease = lifecycle.lease
    outcome = "failed"
    lifecycle.start()
    try:
        container_name = container_manager.ensure_running(project_id)
        healthcheck_outcome = run_intent_healthcheck_gate(
            task_type="explore",
            client=client,
            container_manager=container_manager,
            container_name=container_name,
            project_id=project_id,
            intent_id=intent.id,
            worker=worker,
            command=driver.build_healthcheck(worker),
            timeout_seconds=config.runtime.healthcheck_timeout,
            tty=driver.requires_tty(),
            lease=lease,
            cancellation=cancellation,
            reporter=reporter,
        )
        if healthcheck_outcome is not None:
            outcome = healthcheck_outcome
            return outcome
        task_timeout = project_task_timeout(invocation.execution_config, "explore_conclude", reporter)
        if task_timeout is None:
            best_effort_release(client, project_id, intent.id, worker.name)
            return "failed"
        outcome = run_explore_conclude_fallback(
            config=config,
            client=client,
            container_manager=container_manager,
            worker=worker,
            driver=driver,
            project=project,
            project_id=project_id,
            intent=intent,
            export_yaml=export_yaml,
            session=session_id,
            lease=lease,
            cancellation=cancellation,
            reporter=reporter,
            conclude_timeout=int(task_timeout["conclude_timeout"]),
            capability_context=None,
            execution_config=invocation.execution_config,
        )
        return outcome
    except Exception:
        LOG.exception("explore conclude-only task crashed project=%s intent=%s worker=%s", project_id, intent.id, worker.name)
        best_effort_release(client, project_id, intent.id, worker.name)
        reporter.emit_error("explore_conclude", "error", "task crashed")
        return "failed"
    finally:
        lifecycle.finish(outcome)
