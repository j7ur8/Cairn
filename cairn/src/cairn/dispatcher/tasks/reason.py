from __future__ import annotations

import logging
import time

from cairn.dispatcher.tasks.context import TaskInvocation, TaskServices
from cairn.dispatcher.tasks.lifecycle import TaskLifecycle, TaskRunContext
from cairn.dispatcher.tasks.reason_prompt import build_reason_execute_prompt
from cairn.dispatcher.tasks.reason_result import apply_reason_result
from cairn.dispatcher.tasks.runner import prepare_task_execution
from cairn.dispatcher.tasks.task_outcome import cancel_reason, did_timeout
from cairn.dispatcher.tasks.task_process import run_healthcheck, run_worker_process
from cairn.dispatcher.tasks.task_release import best_effort_release_reason
from cairn.dispatcher.tasks.task_text import preview
from cairn.dispatcher.workers.registry import get_driver

LOG = logging.getLogger(__name__)


def run_reason_task(
    services: TaskServices,
    invocation: TaskInvocation,
) -> str:
    config = services.config
    client = services.client
    container_manager = services.container_runtime
    project = invocation.project
    worker = invocation.worker
    execution_config = invocation.execution_config
    export_yaml = invocation.export_yaml
    assert export_yaml is not None
    reason_run_id = invocation.reason_run_id
    reason_trigger = invocation.reason_trigger
    reason_trigger_hash = invocation.reason_trigger_hash
    assert reason_run_id is not None
    assert reason_trigger is not None
    assert reason_trigger_hash is not None
    fact_count = invocation.fact_count
    hint_count = invocation.hint_count
    open_intent_count = invocation.open_intent_count
    cancellation = invocation.cancellation
    driver = get_driver(worker.type)
    lifecycle = TaskLifecycle(
        TaskRunContext(
            config=config,
            client=client,
            project_id=project.project.id,
            task_type="reason",
            worker=worker,
            intent_id=None,
            reason_run_id=reason_run_id,
        )
    )
    reporter = lifecycle.reporter
    outcome = "failed"
    reason_finish_outcome = "failed"
    reason_finish_error: str | None = None
    task_started = time.perf_counter()
    healthcheck_timeout = config.runtime.healthcheck_timeout
    lease = lifecycle.lease
    lifecycle.start()
    try:
        container_name = container_manager.ensure_running(project.project.id)

        LOG.info(
            "starting container exec project=%s worker=%s phase=reason_healthcheck timeout=%ss",
            project.project.id,
            worker.name,
            healthcheck_timeout,
        )
        healthcheck = run_healthcheck(
            container_manager,
            container_name,
            worker,
            driver.build_healthcheck(worker),
            timeout_seconds=healthcheck_timeout,
            tty=driver.requires_tty(),
            lease=lease,
            cancellation=cancellation,
        )
        cancelled = cancel_reason(healthcheck.result, cancellation)
        if cancelled is not None:
            LOG.info(
                "reason cancelled during healthcheck project=%s worker=%s reason=%s",
                project.project.id,
                worker.name,
                cancelled,
            )
            outcome = "cancelled"
            reason_finish_outcome = "cancelled"
            reason_finish_error = cancelled
            reporter.emit_error("reason_healthcheck", "cancelled", cancelled)
            return outcome
        if lease.failure is not None:
            LOG.warning(
                "heartbeat lost during reason healthcheck project=%s worker=%s status=%s",
                project.project.id,
                worker.name,
                lease.failure.status_code,
            )
            outcome = "failed"
            reason_finish_outcome = "failed"
            reason_finish_error = f"heartbeat lost status={lease.failure.status_code}"
            reporter.emit_error("reason_healthcheck", "error", f"heartbeat lost status={lease.failure.status_code}")
            return outcome
        if healthcheck.result.returncode != 0:
            LOG.warning(
                "worker unhealthy project=%s worker=%s healthcheck_ms=%s stderr=%s",
                project.project.id,
                worker.name,
                healthcheck.duration_ms,
                preview(healthcheck.result.stderr),
            )
            outcome = "unhealthy"
            reason_finish_outcome = "unhealthy"
            reason_finish_error = preview(healthcheck.result.stderr)
            reporter.emit_error("reason_healthcheck", "error", healthcheck.result.stderr)
            return outcome
        prepared = prepare_task_execution(
            config=config,
            client=client,
            container_manager=container_manager,
            container_name=container_name,
            project_id=project.project.id,
            task_type="reason",
            capability_scope=f"reason-{worker.name}-{reason_run_id[:12]}",
            reporter=reporter,
            phase="reason_execute",
            preloaded_execution_config=execution_config,
        )
        if prepared is None:
            outcome = "failed"
            reason_finish_outcome = "failed"
            reason_finish_error = "execution config missing task_timeout"
            return outcome
        task_timeout = prepared.task_timeout
        capabilities = prepared.capabilities
        prompt, open_intents, _allowed_fact_ids = build_reason_execute_prompt(
            config=config,
            container_manager=container_manager,
            container_name=container_name,
            project=project,
            export_yaml=export_yaml,
            prepared=prepared,
            worker=worker,
        )
        reporter.emit_prompt("reason_execute", prompt)

        session = driver.prepare_session()
        command = driver.build_execute(worker, prompt, session, capabilities.context)
        execute_started = time.perf_counter()
        result = run_worker_process(
            container_manager,
            container_name,
            worker,
            command.argv,
            phase="reason_execute",
            timeout_seconds=int(task_timeout["timeout"]),
            tty=driver.requires_tty(),
            lease=lease,
            cancellation=cancellation,
            reporter=reporter,
            trace_format=driver.trace_format(),
        )
        execute_ms = int((time.perf_counter() - execute_started) * 1000)
        total_ms = int((time.perf_counter() - task_started) * 1000)
        session = driver.extract_session(session, result.stdout, result.stderr)
        cancelled = cancel_reason(result, cancellation)
        if cancelled is not None:
            LOG.info(
                "reason cancelled project=%s worker=%s reason=%s execute_ms=%s",
                project.project.id,
                worker.name,
                cancelled,
                execute_ms,
            )
            outcome = "cancelled"
            reason_finish_outcome = "cancelled"
            reason_finish_error = cancelled
            reporter.emit_error("reason_execute", "cancelled", cancelled)
            return outcome
        if lease.failure is not None:
            LOG.warning(
                "heartbeat lost during reason project=%s worker=%s status=%s execute_ms=%s",
                project.project.id,
                worker.name,
                lease.failure.status_code,
                execute_ms,
            )
            outcome = "failed"
            reason_finish_outcome = "failed"
            reason_finish_error = f"heartbeat lost status={lease.failure.status_code}"
            reporter.emit_error("reason_execute", "error", f"heartbeat lost status={lease.failure.status_code}")
            return outcome
        if did_timeout(result):
            LOG.warning(
                "reason timed out project=%s worker=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
                project.project.id,
                worker.name,
                execute_ms,
                total_ms,
                preview(result.stdout),
                preview(result.stderr),
            )
            outcome = "timeout"
            reason_finish_outcome = "timeout"
            reason_finish_error = preview(result.stderr or result.stdout)
            reporter.emit_error("reason_execute", "timeout", preview(result.stderr or result.stdout))
            return outcome
        if result.returncode != 0:
            LOG.warning(
                "reason command failed project=%s worker=%s code=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
                project.project.id,
                worker.name,
                result.returncode,
                execute_ms,
                total_ms,
                preview(result.stdout),
                preview(result.stderr),
            )
            outcome = "failed"
            reason_finish_outcome = "failed"
            reason_finish_error = f"command failed returncode={result.returncode}"
            reporter.emit_error("reason_execute", "error", f"command failed returncode={result.returncode}\n{result.stderr}")
            return outcome
        step = apply_reason_result(
            client=client,
            driver=driver,
            project_id=project.project.id,
            worker_name=worker.name,
            result=result,
            open_intents=open_intents,
            max_intents=config.tasks.reason.max_intents,
            execute_ms=execute_ms,
            total_ms=total_ms,
            reporter=reporter,
        )
        outcome = step.outcome
        reason_finish_outcome = step.finish_outcome
        reason_finish_error = step.finish_error
        return outcome
    finally:
        finish = client.finish_reason(
            project.project.id,
            worker.name,
            run_id=reason_run_id,
            trigger=reason_trigger,
            trigger_hash=reason_trigger_hash,
            fact_count=fact_count,
            hint_count=hint_count,
            open_intent_count=open_intent_count,
            outcome=reason_finish_outcome,
            error=reason_finish_error,
        )
        if not finish.ok and finish.status_code not in (403, 409):
            LOG.warning(
                "reason finish state write failed project=%s worker=%s status=%s body=%s",
                project.project.id,
                worker.name,
                finish.status_code,
                finish.text,
            )
        lifecycle.finish(outcome)
        best_effort_release_reason(client, project.project.id, worker.name, reason_run_id)
