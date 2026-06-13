from __future__ import annotations

import logging
import time

from cairn.dispatcher.contracts import parse_json_output, validate_explore_payload
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.tasks.explore_prompt import build_explore_execute_prompt
from cairn.dispatcher.tasks.explore_result import run_explore_conclude_fallback
from cairn.dispatcher.tasks.healthcheck_gate import run_intent_healthcheck_gate
from cairn.dispatcher.tasks.lifecycle import TaskLifecycle, TaskRunContext
from cairn.dispatcher.tasks.process_runner import run_task_process
from cairn.dispatcher.tasks.runner import prepare_task_execution
from cairn.dispatcher.tasks.task_outcome import cancel_reason, did_timeout
from cairn.dispatcher.tasks.task_release import best_effort_release
from cairn.dispatcher.tasks.task_text import preview
from cairn.dispatcher.tasks.task_writeback import write_conclude_result_with_fact_id
from cairn.dispatcher.workers.registry import get_driver
from cairn.shared.config import DispatchConfig, WorkerConfig
from cairn.shared.contracts import Intent, ProjectDetail

LOG = logging.getLogger(__name__)


def run_explore_task(
    config: DispatchConfig,
    client: CairnClient,
    container_manager: ContainerManager,
    project: ProjectDetail,
    export_yaml: str,
    intent: Intent,
    worker: WorkerConfig,
    execution_config: dict,
    cancellation: TaskCancellation,
) -> str:
    driver = get_driver(worker.type)
    lifecycle = TaskLifecycle(
        TaskRunContext(
            config=config,
            client=client,
            project_id=project.project.id,
            task_type="explore",
            worker=worker,
            intent_id=intent.id,
        )
    )
    reporter = lifecycle.reporter
    outcome = "failed"
    task_started = time.perf_counter()
    healthcheck_timeout = config.runtime.healthcheck_timeout
    lease = lifecycle.lease
    lifecycle.start()
    try:
        container_name = container_manager.ensure_running(project.project.id)

        healthcheck_outcome = run_intent_healthcheck_gate(
            task_type="explore",
            client=client,
            container_manager=container_manager,
            container_name=container_name,
            project_id=project.project.id,
            intent_id=intent.id,
            worker=worker,
            command=driver.build_healthcheck(worker),
            timeout_seconds=healthcheck_timeout,
            tty=driver.requires_tty(),
            lease=lease,
            cancellation=cancellation,
            reporter=reporter,
        )
        if healthcheck_outcome is not None:
            outcome = healthcheck_outcome
            return outcome

        prepared = prepare_task_execution(
            config=config,
            client=client,
            container_manager=container_manager,
            container_name=container_name,
            project_id=project.project.id,
            task_type="explore",
            capability_scope=f"explore-{intent.id}",
            reporter=reporter,
            phase="explore_execute",
            preloaded_execution_config=execution_config,
        )
        if prepared is None:
            best_effort_release(client, project.project.id, intent.id, worker.name)
            outcome = "failed"
            return outcome
        task_timeout = prepared.task_timeout
        capabilities = prepared.capabilities

        prompt = build_explore_execute_prompt(
            config=config,
            container_manager=container_manager,
            container_name=container_name,
            export_yaml=export_yaml,
            intent=intent,
            prepared=prepared,
        )
        reporter.emit_prompt("explore_execute", prompt)

        session = driver.prepare_session()
        execute = driver.build_execute(worker, prompt, session, capabilities.context)
        session = execute.session
        execute_started = time.perf_counter()
        first = run_task_process(
            container_manager,
            container_name,
            worker,
            execute.argv,
            phase="explore_execute",
            timeout=int(task_timeout["timeout"]),
            lease=lease,
            cancellation=cancellation,
            reporter=reporter,
            tty=driver.requires_tty(),
            trace_format=driver.trace_format(),
        )
        execute_ms = int((time.perf_counter() - execute_started) * 1000)
        session = driver.extract_session(session, first.stdout, first.stderr)
        cancelled = cancel_reason(first, cancellation)
        if cancelled is not None:
            LOG.info(
                "explore cancelled project=%s intent=%s worker=%s reason=%s execute_ms=%s",
                project.project.id,
                intent.id,
                worker.name,
                cancelled,
                execute_ms,
            )
            best_effort_release(client, project.project.id, intent.id, worker.name)
            outcome = "cancelled"
            reporter.emit_error("explore_execute", "cancelled", cancelled)
            return outcome
        if lease.failure is not None:
            LOG.warning(
                "heartbeat lost during explore project=%s intent=%s worker=%s status=%s execute_ms=%s",
                project.project.id,
                intent.id,
                worker.name,
                lease.failure.status_code,
                execute_ms,
            )
            best_effort_release(client, project.project.id, intent.id, worker.name)
            outcome = "failed"
            reporter.emit_error("explore_execute", "error", f"heartbeat lost status={lease.failure.status_code}")
            return outcome
        if not did_timeout(first) and first.returncode == 0:
            try:
                model_output = driver.extract_response_text(first.stdout, first.stderr)
                reporter.emit_result("explore_execute", model_output)
                payload = parse_json_output(model_output)
                kind, description = validate_explore_payload(payload)
            except Exception as exc:
                LOG.warning(
                    "explore parse failed project=%s intent=%s worker=%s error=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
                    project.project.id,
                    intent.id,
                    worker.name,
                    exc,
                    execute_ms,
                    int((time.perf_counter() - task_started) * 1000),
                    preview(first.stdout),
                    preview(first.stderr),
                )
                outcome = run_explore_conclude_fallback(
                    config=config,
                    client=client,
                    container_manager=container_manager,
                    worker=worker,
                    driver=driver,
                    project_id=project.project.id,
                    intent=intent,
                    export_yaml=export_yaml,
                    session=session,
                    lease=lease,
                    cancellation=cancellation,
                    reporter=reporter,
                    conclude_timeout=int(task_timeout["conclude_timeout"]),
                    capability_context=capabilities.context,
                )
                return outcome
            if kind == "rejected":
                LOG.warning(
                    "explore rejected project=%s intent=%s worker=%s execute_ms=%s total_ms=%s stdout_preview=%s",
                    project.project.id,
                    intent.id,
                    worker.name,
                    execute_ms,
                    int((time.perf_counter() - task_started) * 1000),
                    preview(first.stdout),
                )
                best_effort_release(client, project.project.id, intent.id, worker.name)
                outcome = "rejected"
                reporter.emit_error("explore_execute", "error", "model rejected task")
                return outcome
            conclude = write_conclude_result_with_fact_id(
                client,
                project.project.id,
                intent.id,
                worker.name,
                description,
                source="explore_execute",
                phase_ms=execute_ms,
                total_ms=int((time.perf_counter() - task_started) * 1000),
            )
            outcome = conclude.status
            if conclude.fact_id:
                reporter.emit_result("explore_write", description, produced_fact_id=conclude.fact_id)
            return outcome
        if did_timeout(first):
            LOG.warning(
                "explore timed out project=%s intent=%s worker=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
                project.project.id,
                intent.id,
                worker.name,
                execute_ms,
                int((time.perf_counter() - task_started) * 1000),
                preview(first.stdout),
                preview(first.stderr),
            )
            outcome = run_explore_conclude_fallback(
                config=config,
                client=client,
                container_manager=container_manager,
                worker=worker,
                driver=driver,
                project_id=project.project.id,
                intent=intent,
                export_yaml=export_yaml,
                session=session,
                lease=lease,
                cancellation=cancellation,
                reporter=reporter,
                conclude_timeout=int(task_timeout["conclude_timeout"]),
                capability_context=capabilities.context,
            )
            return outcome
        LOG.warning(
            "explore command failed project=%s intent=%s worker=%s code=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
            project.project.id,
            intent.id,
            worker.name,
            first.returncode,
            execute_ms,
            int((time.perf_counter() - task_started) * 1000),
            preview(first.stdout),
            preview(first.stderr),
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        outcome = "failed"
        reporter.emit_error("explore_execute", "error", f"command failed returncode={first.returncode}\n{first.stderr}")
        return outcome
    except Exception:
        LOG.exception("explore task crashed project=%s intent=%s worker=%s", project.project.id, intent.id, worker.name)
        best_effort_release(client, project.project.id, intent.id, worker.name)
        outcome = "failed"
        reporter.emit_error("explore_execute", "error", "task crashed")
        return outcome
    finally:
        lifecycle.finish(outcome)
