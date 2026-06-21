from __future__ import annotations

import logging
import time
from typing import Any

from cairn.dispatcher.contracts import parse_sentinel_fact_output
from cairn.dispatcher.observability.reporter import ExecutionReporter
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.heartbeat import HeartbeatLease
from cairn.dispatcher.tasks.conclude_fallback import ConcludeFallbackRunner
from cairn.dispatcher.tasks.context import ContainerRuntime
from cairn.dispatcher.tasks.explore_prompt import build_explore_conclude_prompt
from cairn.dispatcher.tasks.process_runner import run_task_process
from cairn.dispatcher.tasks.task_outcome import cancel_reason
from cairn.dispatcher.tasks.task_release import best_effort_release
from cairn.dispatcher.tasks.task_text import preview
from cairn.dispatcher.tasks.task_writeback import write_conclude_result_with_fact_id
from cairn.shared.config import DispatchConfig, WorkerConfig
from cairn.shared.contracts import Intent, ProjectDetail

LOG = logging.getLogger(__name__)


def run_explore_conclude_fallback(
    *,
    config: DispatchConfig,
    client: CairnClient,
    container_manager: ContainerRuntime,
    worker: WorkerConfig,
    driver: Any,
    project: ProjectDetail,
    project_id: str,
    intent: Intent,
    export_yaml: str,
    session: str | None,
    lease: HeartbeatLease,
    cancellation: TaskCancellation,
    reporter: ExecutionReporter,
    conclude_timeout: int,
    capability_context: Any = None,
    execution_config: dict | None = None,
) -> str:
    fallback = ConcludeFallbackRunner(
        client=client,
        project_id=project_id,
        intent_id=intent.id,
        worker_name=worker.name,
        phase="explore_conclude",
        lease=lease,
        cancellation=cancellation,
        reporter=reporter,
    )
    preflight = fallback.preflight(supports_conclude=driver.supports_conclude(), has_session=bool(session))
    if preflight is not None:
        return preflight

    container_name = container_manager.ensure_running(project_id)

    prompt = build_explore_conclude_prompt(
        config=config,
        container_manager=container_manager,
        container_name=container_name,
        export_yaml=export_yaml,
        project=project,
        intent=intent,
        execution_config=execution_config,
        reporter=reporter,
    )
    reporter.emit_prompt("explore_conclude", prompt)
    conclude_argv = driver.build_conclude(worker, prompt, session, None)
    LOG.info("starting conclude fallback project=%s intent=%s worker=%s", project_id, intent.id, worker.name)
    conclude_started = time.perf_counter()
    result = run_task_process(
        container_manager,
        container_name,
        worker,
        conclude_argv,
        phase="explore_conclude",
        timeout=conclude_timeout,
        lease=lease,
        cancellation=cancellation,
        reporter=reporter,
        tty=driver.requires_tty(),
        trace_format=driver.trace_format(),
    )
    conclude_ms = int((time.perf_counter() - conclude_started) * 1000)
    cancelled = cancel_reason(result, cancellation)
    if cancelled is not None:
        LOG.info(
            "conclude cancelled project=%s intent=%s worker=%s reason=%s conclude_ms=%s",
            project_id,
            intent.id,
            worker.name,
            cancelled,
            conclude_ms,
        )
        best_effort_release(client, project_id, intent.id, worker.name)
        reporter.emit_error("explore_conclude", "cancelled", cancelled)
        return "cancelled"
    if lease.failure is not None:
        best_effort_release(client, project_id, intent.id, worker.name)
        reporter.emit_error("explore_conclude", "error", f"heartbeat lost status={lease.failure.status_code}")
        return "failed"
    if result.timed_out or result.returncode != 0:
        LOG.warning(
            "conclude failed project=%s intent=%s worker=%s code=%s timed_out=%s conclude_ms=%s stdout_preview=%s stderr_preview=%s",
            project_id,
            intent.id,
            worker.name,
            result.returncode,
            result.timed_out,
            conclude_ms,
            preview(result.stdout),
            preview(result.stderr),
        )
        best_effort_release(client, project_id, intent.id, worker.name)
        reporter.emit_error("explore_conclude", "timeout" if result.timed_out else "error", result.stderr or result.stdout)
        return "failed"
    try:
        model_output = driver.extract_response_text(result.stdout, result.stderr)
        reporter.emit_result("explore_conclude", model_output)
        description = parse_sentinel_fact_output(model_output)
    except Exception as exc:
        LOG.warning(
            "conclude parse failed project=%s intent=%s worker=%s error=%s conclude_ms=%s stdout_preview=%s stderr_preview=%s",
            project_id,
            intent.id,
            worker.name,
            exc,
            conclude_ms,
            preview(result.stdout),
            preview(result.stderr),
        )
        best_effort_release(client, project_id, intent.id, worker.name)
        reporter.emit_error("explore_conclude", "parse_error", str(exc))
        return "failed"
    conclude = write_conclude_result_with_fact_id(
        client,
        project_id,
        intent.id,
        worker.name,
        description,
        source="explore_conclude",
        phase_ms=conclude_ms,
    )
    if conclude.fact_id:
        reporter.emit_result("explore_write", description, produced_fact_id=conclude.fact_id)
    return conclude.status
