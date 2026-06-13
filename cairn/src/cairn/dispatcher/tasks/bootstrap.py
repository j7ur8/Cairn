from __future__ import annotations

import logging
import time

from cairn.dispatcher.contracts import (
    parse_json_output,
    validate_bootstrap_execute_payload,
)
from cairn.dispatcher.prompting import format_remote_support_instructions, load_prompt, render_prompt
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.tasks.bootstrap_prompt import bootstrap_prompt_replacements
from cairn.dispatcher.tasks.bootstrap_result import run_bootstrap_conclude_fallback, write_bootstrap_complete_result
from cairn.dispatcher.tasks.healthcheck_gate import run_intent_healthcheck_gate
from cairn.dispatcher.tasks.lifecycle import TaskLifecycle, TaskRunContext
from cairn.dispatcher.tasks.runner import (
    prepare_task_execution,
)
from cairn.dispatcher.tasks.task_outcome import cancel_reason, did_timeout
from cairn.dispatcher.tasks.task_process import run_worker_process
from cairn.dispatcher.tasks.task_release import best_effort_release
from cairn.dispatcher.tasks.task_text import preview
from cairn.dispatcher.workers.registry import get_driver
from cairn.shared.capability_projection import capability_manifest_payload, project_capability_data
from cairn.shared.config import DispatchConfig, WorkerConfig
from cairn.shared.contracts import Intent, ProjectDetail

LOG = logging.getLogger(__name__)


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
    driver = get_driver(worker.type)
    lifecycle = TaskLifecycle(
        TaskRunContext(
            config=config,
            client=client,
            project_id=project.project.id,
            task_type="bootstrap",
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
            task_type="bootstrap",
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

        capability_data = project_capability_data(execution_config)
        reporter.emit_capability_manifest(
            "bootstrap_start",
            capability_manifest_payload(project.project.id, "bootstrap", capability_data),
        )

        prepared = prepare_task_execution(
            config=config,
            client=client,
            container_manager=container_manager,
            container_name=container_name,
            project_id=project.project.id,
            task_type="bootstrap",
            capability_scope=f"bootstrap-{intent.id}",
            reporter=reporter,
            phase="bootstrap_start",
            preloaded_execution_config=execution_config,
        )
        if prepared is None:
            best_effort_release(client, project.project.id, intent.id, worker.name)
            outcome = "failed"
            return outcome
        task_timeout = prepared.task_timeout
        capabilities = prepared.capabilities
        role = prepared.role

        prompt = render_prompt(
            load_prompt(config.runtime.prompt_group, "bootstrap.md"),
            {
                **bootstrap_prompt_replacements(project),
                "remote_support_instructions": format_remote_support_instructions(config.remote_support),
                "capability_instructions": capabilities.instructions,
                "role_instructions": role.instructions,
            },
        )
        reporter.emit_prompt("bootstrap", prompt)

        session = driver.prepare_session()
        execute = driver.build_execute(worker, prompt, session, capabilities.context)
        session = execute.session
        execute_started = time.perf_counter()
        first = run_worker_process(
            container_manager,
            container_name,
            worker,
            execute.argv,
            phase="bootstrap",
            timeout_seconds=int(task_timeout["timeout"]),
            tty=driver.requires_tty(),
            lease=lease,
            cancellation=cancellation,
            reporter=reporter,
            trace_format=driver.trace_format(),
        )
        execute_ms = int((time.perf_counter() - execute_started) * 1000)
        session = driver.extract_session(session, first.stdout, first.stderr)
        cancelled = cancel_reason(first, cancellation)
        if cancelled is not None:
            LOG.info(
                "bootstrap cancelled project=%s intent=%s worker=%s reason=%s execute_ms=%s",
                project.project.id,
                intent.id,
                worker.name,
                cancelled,
                execute_ms,
            )
            best_effort_release(client, project.project.id, intent.id, worker.name)
            outcome = "cancelled"
            reporter.emit_error("bootstrap", "cancelled", cancelled)
            return outcome
        if lease.failure is not None:
            LOG.warning(
                "heartbeat lost during bootstrap project=%s intent=%s worker=%s status=%s execute_ms=%s",
                project.project.id,
                intent.id,
                worker.name,
                lease.failure.status_code,
                execute_ms,
            )
            best_effort_release(client, project.project.id, intent.id, worker.name)
            outcome = "failed"
            reporter.emit_error("bootstrap", "error", f"heartbeat lost status={lease.failure.status_code}")
            return outcome
        if not did_timeout(first) and first.returncode == 0:
            try:
                model_output = driver.extract_response_text(first.stdout, first.stderr)
                reporter.emit_result("bootstrap", model_output)
                payload = parse_json_output(model_output)
                kind, data = validate_bootstrap_execute_payload(payload)
            except Exception as exc:
                LOG.warning(
                    "bootstrap parse failed project=%s intent=%s worker=%s error=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
                    project.project.id,
                    intent.id,
                    worker.name,
                    exc,
                    execute_ms,
                    int((time.perf_counter() - task_started) * 1000),
                    preview(first.stdout),
                    preview(first.stderr),
                )
                outcome = run_bootstrap_conclude_fallback(
                    config=config,
                    client=client,
                    container_manager=container_manager,
                    worker=worker,
                    driver=driver,
                    project=project,
                    intent=intent,
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
                    "bootstrap rejected project=%s intent=%s worker=%s execute_ms=%s total_ms=%s stdout_preview=%s",
                    project.project.id,
                    intent.id,
                    worker.name,
                    execute_ms,
                    int((time.perf_counter() - task_started) * 1000),
                    preview(first.stdout),
                )
                best_effort_release(client, project.project.id, intent.id, worker.name)
                outcome = "rejected"
                reporter.emit_error("bootstrap", "error", "model rejected task")
                return outcome
            complete = write_bootstrap_complete_result(
                client,
                project.project.id,
                intent.id,
                worker.name,
                data["fact_description"],
                data["complete_description"],
                source="bootstrap",
                phase_ms=execute_ms,
                total_ms=int((time.perf_counter() - task_started) * 1000),
            )
            outcome = complete.status
            if complete.fact_id:
                reporter.emit_result("bootstrap_write", data["complete_description"], produced_fact_id=complete.fact_id)
            return outcome
        if did_timeout(first):
            LOG.warning(
                "bootstrap timed out project=%s intent=%s worker=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
                project.project.id,
                intent.id,
                worker.name,
                execute_ms,
                int((time.perf_counter() - task_started) * 1000),
                preview(first.stdout),
                preview(first.stderr),
            )
            outcome = run_bootstrap_conclude_fallback(
                config=config,
                client=client,
                container_manager=container_manager,
                worker=worker,
                driver=driver,
                project=project,
                intent=intent,
                session=session,
                lease=lease,
                cancellation=cancellation,
                reporter=reporter,
                conclude_timeout=int(task_timeout["conclude_timeout"]),
                capability_context=capabilities.context,
            )
            return outcome
        LOG.warning(
            "bootstrap command failed project=%s intent=%s worker=%s code=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
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
        reporter.emit_error("bootstrap", "error", f"command failed returncode={first.returncode}\n{first.stderr}")
        return outcome
    except Exception:
        LOG.exception("bootstrap task crashed project=%s intent=%s worker=%s", project.project.id, intent.id, worker.name)
        best_effort_release(client, project.project.id, intent.id, worker.name)
        outcome = "failed"
        reporter.emit_error("bootstrap", "error", "task crashed")
        return outcome
    finally:
        lifecycle.finish(outcome)
