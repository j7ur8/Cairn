"""Shared template for the per-intent task runners (bootstrap, explore).

bootstrap and explore drove the same lifecycle through ~90% identical code:
healthcheck gate -> prepare -> build prompt -> run worker process ->
cancellation / heartbeat / timeout / command-failure / parse-failure
branches -> success write or conclude fallback -> finish. The only real
differences are the prompt, the payload validator, the success writer, the
conclude fallback, and a few phase-name strings.

This module captures the skeleton once. Each task type supplies an
``IntentTaskSpec`` of hooks; ``run_intent_task`` runs the lifecycle. ``reason``
is intentionally NOT built on this template — it has no healthcheck gate, no
conclude fallback, a different finally/release protocol, and a distinct
result path, so sharing would add more branching than it removes.

Behavior is pinned by tests/test_task_runner_characterization.py.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.process import ProcessResult
from cairn.dispatcher.tasks.context import ContainerRuntime, TaskInvocation, TaskServices
from cairn.dispatcher.tasks.healthcheck_gate import run_intent_healthcheck_gate
from cairn.dispatcher.tasks.lifecycle import TaskLifecycle, TaskRunContext
from cairn.dispatcher.tasks.runner import PreparedTaskExecution, prepare_task_execution
from cairn.dispatcher.tasks.task_outcome import cancel_reason, did_timeout
from cairn.dispatcher.tasks.task_process import run_worker_process
from cairn.dispatcher.tasks.task_release import best_effort_release
from cairn.dispatcher.tasks.task_text import preview
from cairn.dispatcher.workers.registry import get_driver
from cairn.shared.config import DispatchConfig, WorkerConfig
from cairn.shared.contracts import Intent, ProjectDetail

LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class IntentTaskContext:
    """Everything the per-type hooks need; built by the template."""

    config: DispatchConfig
    client: CairnClient
    container_manager: ContainerRuntime
    container_name: str
    project: ProjectDetail
    intent: Intent
    worker: WorkerConfig
    export_yaml: str | None
    prepared: PreparedTaskExecution
    driver: Any
    session: Any
    reporter: Any
    execute_ms: int
    total_ms: int
    lease: Any
    cancellation: TaskCancellation


@dataclass(slots=True)
class IntentWriteOutcome:
    """Result of a successful-parse success write."""

    outcome: str
    fact_id: str | None
    result_phase: str
    result_description: str


@dataclass(slots=True)
class IntentTaskSpec:
    task_type: str
    exec_phase: str
    prepare_phase: str
    capability_scope: Callable[[Intent], str]
    build_prompt: Callable[[IntentTaskContext], str]
    # parse + validate the raw model output; raises on bad output (caught by
    # the template, which then runs the conclude fallback). Returns
    # (kind, payload) where kind == "rejected" short-circuits.
    validate: Callable[[str], tuple[str, Any]]
    write_success: Callable[[IntentTaskContext, Any], IntentWriteOutcome]
    conclude_fallback: Callable[[IntentTaskContext], str]
    # Optional pre-prepare hook (bootstrap emits a capability manifest here).
    # Called with (reporter, project, execution_config).
    emit_capability_manifest: Callable[[Any, ProjectDetail, dict], None] | None = None


def run_intent_task(
    spec: IntentTaskSpec,
    services: TaskServices,
    invocation: TaskInvocation,
) -> str:
    config = services.config
    client = services.client
    container_manager = services.container_runtime
    project = invocation.project
    intent = invocation.intent
    assert intent is not None
    worker = invocation.worker
    execution_config = invocation.execution_config
    cancellation = invocation.cancellation
    export_yaml = invocation.export_yaml
    project_id = project.project.id
    if cancellation.reason is not None:
        best_effort_release(client, project_id, intent.id, worker.name)
        return "cancelled"
    driver = get_driver(worker.type)
    lifecycle = TaskLifecycle(
        TaskRunContext(
            config=config,
            client=client,
            project_id=project_id,
            task_type=spec.task_type,
            worker=worker,
            intent_id=intent.id,
        )
    )
    reporter = lifecycle.reporter
    outcome = "failed"
    task_started = time.perf_counter()
    lease = lifecycle.lease
    prepared = None
    lifecycle.start()
    try:
        _emit_cloak_sidecar_event(reporter, spec.prepare_phase, execution_config)
        container_name = container_manager.ensure_running(project_id)
        cancelled = _cancelled_before_exec(cancellation, spec.task_type, project_id, intent.id, worker.name, spec.exec_phase, reporter)
        if cancelled is not None:
            best_effort_release(client, project_id, intent.id, worker.name)
            outcome = "cancelled"
            return outcome

        healthcheck_outcome = run_intent_healthcheck_gate(
            task_type=spec.task_type,
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
        cancelled = _cancelled_before_exec(cancellation, spec.task_type, project_id, intent.id, worker.name, spec.exec_phase, reporter)
        if cancelled is not None:
            best_effort_release(client, project_id, intent.id, worker.name)
            outcome = "cancelled"
            return outcome

        if spec.emit_capability_manifest is not None:
            spec.emit_capability_manifest(reporter, project, execution_config)

        prepared = prepare_task_execution(
            config=config,
            client=client,
            container_manager=container_manager,
            container_name=container_name,
            project_id=project_id,
            task_type=spec.task_type,
            capability_scope=spec.capability_scope(intent),
            reporter=reporter,
            phase=spec.prepare_phase,
            project=project,
            cloak_sidecar_manager=services.cloak_sidecar_manager,
            preloaded_execution_config=execution_config,
        )
        if prepared is None:
            best_effort_release(client, project_id, intent.id, worker.name)
            outcome = "failed"
            return outcome
        task_timeout = prepared.task_timeout

        session = driver.prepare_session()
        ctx = IntentTaskContext(
            config=config, client=client, container_manager=container_manager,
            container_name=container_name, project=project, intent=intent,
            worker=worker, export_yaml=export_yaml, prepared=prepared,
            driver=driver, session=session, reporter=reporter,
            execute_ms=0, total_ms=0, lease=lease, cancellation=cancellation,
        )
        prompt = spec.build_prompt(ctx)
        reporter.emit_prompt(spec.exec_phase, prompt)
        cancelled = _cancelled_before_exec(cancellation, spec.task_type, project_id, intent.id, worker.name, spec.exec_phase, reporter)
        if cancelled is not None:
            best_effort_release(client, project_id, intent.id, worker.name)
            outcome = "cancelled"
            return outcome

        execute = driver.build_execute(worker, prompt, session, prepared.capabilities.context)
        ctx.session = execute.session
        execute_started = time.perf_counter()
        first = run_worker_process(
            container_manager,
            container_name,
            worker,
            execute.argv,
            phase=spec.exec_phase,
            timeout_seconds=int(task_timeout["timeout"]),
            workdir=execute.workdir,
            tty=driver.requires_tty(),
            lease=lease,
            cancellation=cancellation,
            reporter=reporter,
            trace_format=driver.trace_format(),
        )
        execute_ms = int((time.perf_counter() - execute_started) * 1000)
        ctx.session = driver.extract_session(ctx.session, first.stdout, first.stderr)
        ctx.execute_ms = execute_ms
        outcome = _handle_result(spec, ctx, first, lease, cancellation, task_started)
        return outcome
    except Exception:
        LOG.exception("%s task crashed project=%s intent=%s worker=%s", spec.task_type, project_id, intent.id, worker.name)
        best_effort_release(client, project_id, intent.id, worker.name)
        outcome = "failed"
        reporter.emit_error(spec.exec_phase, "error", "task crashed")
        return outcome
    finally:
        if prepared is not None:
            prepared.capabilities.release_runtime_leases()
        container_manager.finish()
        lifecycle.finish(outcome)


def _emit_cloak_sidecar_event(reporter: Any, phase: str, execution_config: dict) -> None:
    sidecar = execution_config.get("cloak_sidecar")
    if not isinstance(sidecar, dict):
        return
    payload = {
        "running": bool(sidecar.get("running")),
        "novnc_url": sidecar.get("novnc_url"),
        "slots": sidecar.get("slots"),
        "busy_slots": sidecar.get("busy_slots"),
        "container_name": sidecar.get("container_name"),
    }
    reporter.emit_result(phase, json.dumps({"cloak_sidecar": payload}, ensure_ascii=False, indent=2))


def _cancelled_before_exec(
    cancellation: TaskCancellation,
    task_type: str,
    project_id: str,
    intent_id: str,
    worker_name: str,
    phase: str,
    reporter: Any,
) -> str | None:
    cancelled = cancellation.reason
    if cancelled is None:
        return None
    LOG.info(
        "%s cancelled before container exec project=%s intent=%s worker=%s reason=%s",
        task_type,
        project_id,
        intent_id,
        worker_name,
        cancelled,
    )
    reporter.emit_error(phase, "cancelled", cancelled)
    return cancelled


# Exceptions treated as "bad model output" -> conclude fallback. Anything
# else (programming errors, infra failures) propagates to the task-level
# crash handler instead of being silently funneled into the fallback.
_PARSE_FAILURE_EXCEPTIONS = (ValueError, KeyError, TypeError)


def _handle_result(
    spec: IntentTaskSpec,
    ctx: IntentTaskContext,
    first: ProcessResult,
    lease: Any,
    cancellation: TaskCancellation,
    task_started: float,
) -> str:
    project_id = ctx.project.project.id
    intent = ctx.intent
    worker = ctx.worker
    client = ctx.client
    reporter = ctx.reporter
    driver = ctx.driver
    execute_ms = ctx.execute_ms

    cancelled = cancel_reason(first, cancellation)
    if cancelled is not None:
        LOG.info(
            "%s cancelled project=%s intent=%s worker=%s reason=%s execute_ms=%s",
            spec.task_type, project_id, intent.id, worker.name, cancelled, execute_ms,
        )
        best_effort_release(client, project_id, intent.id, worker.name)
        reporter.emit_error(spec.exec_phase, "cancelled", cancelled)
        return "cancelled"
    if lease.failure is not None:
        LOG.warning(
            "heartbeat lost during %s project=%s intent=%s worker=%s status=%s execute_ms=%s",
            spec.task_type, project_id, intent.id, worker.name, lease.failure.status_code, execute_ms,
        )
        best_effort_release(client, project_id, intent.id, worker.name)
        reporter.emit_error(spec.exec_phase, "error", f"heartbeat lost status={lease.failure.status_code}")
        return "failed"
    if not did_timeout(first) and first.returncode == 0:
        try:
            model_output = driver.extract_response_text(first.stdout, first.stderr)
            reporter.emit_result(spec.exec_phase, model_output)
            kind, payload = spec.validate(model_output)
        except _PARSE_FAILURE_EXCEPTIONS as exc:
            ctx.total_ms = int((time.perf_counter() - task_started) * 1000)
            LOG.warning(
                "%s parse failed project=%s intent=%s worker=%s error=%s(%s) execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
                spec.task_type, project_id, intent.id, worker.name, type(exc).__name__, exc,
                execute_ms, ctx.total_ms, preview(first.stdout), preview(first.stderr),
            )
            return spec.conclude_fallback(ctx)
        if kind == "rejected":
            LOG.warning(
                "%s rejected project=%s intent=%s worker=%s execute_ms=%s total_ms=%s stdout_preview=%s",
                spec.task_type, project_id, intent.id, worker.name, execute_ms,
                int((time.perf_counter() - task_started) * 1000), preview(first.stdout),
            )
            best_effort_release(client, project_id, intent.id, worker.name)
            reporter.emit_error(spec.exec_phase, "error", "model rejected task")
            return "rejected"
        ctx.total_ms = int((time.perf_counter() - task_started) * 1000)
        written = spec.write_success(ctx, payload)
        if written.fact_id:
            reporter.emit_result(written.result_phase, written.result_description, produced_fact_id=written.fact_id)
        return written.outcome
    if did_timeout(first):
        LOG.warning(
            "%s timed out project=%s intent=%s worker=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
            spec.task_type, project_id, intent.id, worker.name, execute_ms,
            int((time.perf_counter() - task_started) * 1000), preview(first.stdout), preview(first.stderr),
        )
        return spec.conclude_fallback(ctx)
    LOG.warning(
        "%s command failed project=%s intent=%s worker=%s code=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
        spec.task_type, project_id, intent.id, worker.name, first.returncode, execute_ms,
        int((time.perf_counter() - task_started) * 1000), preview(first.stdout), preview(first.stderr),
    )
    best_effort_release(client, project_id, intent.id, worker.name)
    reporter.emit_error(spec.exec_phase, "error", f"command failed returncode={first.returncode}\n{first.stderr}")
    return "failed"
