from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from cairn.dispatcher.contracts import parse_sentinel_fact_output
from cairn.dispatcher.observability.reporter import ExecutionReporter
from cairn.dispatcher.prompting import load_prompt, render_prompt
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.heartbeat import HeartbeatLease
from cairn.dispatcher.tasks.bootstrap_prompt import bootstrap_prompt_replacements
from cairn.dispatcher.tasks.conclude_fallback import ConcludeFallbackRunner
from cairn.dispatcher.tasks.context import ContainerRuntime
from cairn.dispatcher.tasks.task_outcome import cancel_reason
from cairn.dispatcher.tasks.task_process import run_worker_process
from cairn.dispatcher.tasks.task_release import best_effort_release
from cairn.dispatcher.tasks.task_text import preview
from cairn.dispatcher.tasks.task_writeback import write_conclude_result_with_fact_id
from cairn.shared.config import DispatchConfig, WorkerConfig
from cairn.shared.contracts import Intent, ProjectDetail

LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class BootstrapCompleteWriteResult:
    status: str
    fact_id: str | None = None


def write_bootstrap_complete_result(
    client: CairnClient,
    project_id: str,
    intent_id: str,
    worker_name: str,
    fact_description: str,
    complete_description: str,
    *,
    source: str,
    phase_ms: int,
    total_ms: int | None = None,
) -> BootstrapCompleteWriteResult:
    conclude = write_conclude_result_with_fact_id(
        client,
        project_id,
        intent_id,
        worker_name,
        fact_description,
        source=source,
        phase_ms=phase_ms,
        total_ms=total_ms,
    )
    if conclude.status != "success":
        return BootstrapCompleteWriteResult(status="failed")
    if conclude.fact_id is None:
        LOG.warning(
            "bootstrap complete deferred because conclude response omitted fact id project=%s intent=%s worker=%s source=%s",
            project_id,
            intent_id,
            worker_name,
            source,
        )
        return BootstrapCompleteWriteResult(status="success", fact_id=None)

    response = client.complete(project_id, [conclude.fact_id], complete_description, worker_name)
    if response.status_code in (403, 409):
        LOG.info(
            "bootstrap complete deferred project=%s intent=%s worker=%s source=%s status=%s fact_id=%s",
            project_id,
            intent_id,
            worker_name,
            source,
            response.status_code,
            conclude.fact_id,
        )
        return BootstrapCompleteWriteResult(status="success", fact_id=conclude.fact_id)
    if not response.ok:
        LOG.warning(
            "bootstrap complete write failed project=%s intent=%s worker=%s source=%s fact_id=%s status=%s body=%s",
            project_id,
            intent_id,
            worker_name,
            source,
            conclude.fact_id,
            response.status_code,
            response.text,
        )
        return BootstrapCompleteWriteResult(status="success", fact_id=conclude.fact_id)
    if total_ms is None:
        LOG.info(
            "bootstrap completed project=%s intent=%s worker=%s source=%s from=%s phase_ms=%s",
            project_id,
            intent_id,
            worker_name,
            source,
            [conclude.fact_id],
            phase_ms,
        )
    else:
        LOG.info(
            "bootstrap completed project=%s intent=%s worker=%s source=%s from=%s phase_ms=%s total_ms=%s",
            project_id,
            intent_id,
            worker_name,
            source,
            [conclude.fact_id],
            phase_ms,
            total_ms,
        )
    return BootstrapCompleteWriteResult(status="success", fact_id=conclude.fact_id)


def run_bootstrap_conclude_fallback(
    *,
    config: DispatchConfig,
    client: CairnClient,
    container_manager: ContainerRuntime,
    worker: WorkerConfig,
    driver: Any,
    project: ProjectDetail,
    intent: Intent,
    session: str | None,
    lease: HeartbeatLease,
    cancellation: TaskCancellation,
    reporter: ExecutionReporter,
    conclude_timeout: int,
    capability_context: Any = None,
) -> str:
    fallback = ConcludeFallbackRunner(
        client=client,
        project_id=project.project.id,
        intent_id=intent.id,
        worker_name=worker.name,
        phase="bootstrap_conclude",
        lease=lease,
        cancellation=cancellation,
        reporter=reporter,
    )
    preflight = fallback.preflight(supports_conclude=driver.supports_conclude(), has_session=bool(session))
    if preflight is not None:
        return preflight

    container_name = container_manager.ensure_running(project.project.id)

    prompt = render_prompt(
        load_prompt(config.runtime.prompt_group, "bootstrap_conclude.md"),
        bootstrap_prompt_replacements(project),
    )
    reporter.emit_prompt("bootstrap_conclude", prompt)
    conclude_argv = driver.build_conclude(worker, prompt, session, None)
    LOG.info("starting bootstrap conclude fallback project=%s intent=%s worker=%s", project.project.id, intent.id, worker.name)
    conclude_started = time.perf_counter()
    result = run_worker_process(
        container_manager,
        container_name,
        worker,
        conclude_argv,
        phase="bootstrap_conclude",
        timeout_seconds=conclude_timeout,
        tty=driver.requires_tty(),
        lease=lease,
        cancellation=cancellation,
        reporter=reporter,
        trace_format=driver.trace_format(),
    )
    conclude_ms = int((time.perf_counter() - conclude_started) * 1000)
    cancelled = cancel_reason(result, cancellation)
    if cancelled is not None:
        LOG.info(
            "bootstrap conclude cancelled project=%s intent=%s worker=%s reason=%s conclude_ms=%s",
            project.project.id,
            intent.id,
            worker.name,
            cancelled,
            conclude_ms,
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        reporter.emit_error("bootstrap_conclude", "cancelled", cancelled)
        return "cancelled"
    if lease.failure is not None:
        best_effort_release(client, project.project.id, intent.id, worker.name)
        reporter.emit_error("bootstrap_conclude", "error", f"heartbeat lost status={lease.failure.status_code}")
        return "failed"
    if result.timed_out or result.returncode != 0:
        LOG.warning(
            "bootstrap conclude failed project=%s intent=%s worker=%s code=%s timed_out=%s conclude_ms=%s stdout_preview=%s stderr_preview=%s",
            project.project.id,
            intent.id,
            worker.name,
            result.returncode,
            result.timed_out,
            conclude_ms,
            preview(result.stdout),
            preview(result.stderr),
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        reporter.emit_error("bootstrap_conclude", "timeout" if result.timed_out else "error", result.stderr or result.stdout)
        return "failed"
    try:
        model_output = driver.extract_response_text(result.stdout, result.stderr)
        reporter.emit_result("bootstrap_conclude", model_output)
        fact_description = parse_sentinel_fact_output(model_output)
    except Exception as exc:
        LOG.warning(
            "bootstrap conclude parse failed project=%s intent=%s worker=%s error=%s conclude_ms=%s stdout_preview=%s stderr_preview=%s",
            project.project.id,
            intent.id,
            worker.name,
            exc,
            conclude_ms,
            preview(result.stdout),
            preview(result.stderr),
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        reporter.emit_error("bootstrap_conclude", "parse_error", str(exc))
        return "failed"
    conclude = write_conclude_result_with_fact_id(
        client,
        project.project.id,
        intent.id,
        worker.name,
        fact_description,
        source="bootstrap_conclude",
        phase_ms=conclude_ms,
    )
    if conclude.fact_id:
        reporter.emit_result("bootstrap_write", fact_description, produced_fact_id=conclude.fact_id)
    return conclude.status
