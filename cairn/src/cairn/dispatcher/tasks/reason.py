from __future__ import annotations

import logging
import time
import uuid

from cairn.dispatcher.config import DispatchConfig, WorkerConfig
from cairn.dispatcher.capabilities import inject_project_capabilities
from cairn.dispatcher.roles import inject_project_role
from cairn.dispatcher.contracts import parse_json_output, validate_reason_payload
from cairn.dispatcher.observability.reporter import ExecutionReporter
from cairn.dispatcher.prompting import (
    format_fact_ids,
    format_open_intents,
    load_prompt,
    render_prompt,
)
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.runtime.heartbeat import HeartbeatLease
from cairn.dispatcher.tasks.common import (
    best_effort_release_reason,
    cancel_reason,
    did_timeout,
    preview,
    process_state_for_task_outcome,
    run_healthcheck,
    run_worker_process,
    write_graph_snapshot_reference,
)
from cairn.dispatcher.workers.registry import get_driver
from cairn.server.models import ProjectDetail

LOG = logging.getLogger(__name__)


def run_reason_task(
    config: DispatchConfig,
    client: CairnClient,
    container_manager: ContainerManager,
    project: ProjectDetail,
    export_yaml: str,
    worker: WorkerConfig,
    cancellation: TaskCancellation,
) -> str:
    driver = get_driver(worker.type)
    reporter = ExecutionReporter(
        client,
        config.observability,
        project_id=project.project.id,
        intent_id=None,
        task_type="reason",
        worker=worker.name,
    ) if config.observability.enabled else ExecutionReporter.disabled()
    reporter.start()
    outcome = "failed"
    task_started = time.perf_counter()
    healthcheck_timeout = config.runtime.healthcheck_timeout
    lease = HeartbeatLease.for_reason(client, project.project.id, worker.name, config.runtime.interval)
    lease.start()
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
            reporter.emit_error("reason_healthcheck", "error", healthcheck.result.stderr)
            return outcome
        capabilities = inject_project_capabilities(
            config,
            container_manager,
            container_name,
            project.project.id,
            "reason",
            f"reason-{worker.name}-{uuid.uuid4().hex[:12]}",
            _project_capability_data(client, project.project.id, reporter, "reason_execute"),
        )
        if capabilities.summary:
            reporter.emit_result("capabilities", capabilities.summary)
        for error in capabilities.errors:
            reporter.emit_error("capabilities", "error", error)
        role = inject_project_role(
            project.project.id,
            "reason",
            _project_role_data(client, project.project.id, reporter, "reason_execute"),
        )
        if role.summary:
            reporter.emit_result("role", role.summary)
        for error in role.errors or []:
            reporter.emit_error("role", "error", error)
        open_intents = [
            {
                "id": intent.id,
                "from": intent.from_,
                "description": intent.description,
                "worker": intent.worker,
            }
            for intent in project.intents
            if intent.to is None
        ]
        allowed_fact_ids = [fact.id for fact in project.facts if fact.id != "goal"]
        LOG.debug(
            "reason context prepared project=%s worker=%s facts=%s allowed_fact_ids=%s hints=%s open_intents=%s",
            project.project.id,
            worker.name,
            len(project.facts),
            len(allowed_fact_ids),
            len(project.hints),
            len(open_intents),
        )
        prompt = render_prompt(
            load_prompt(config.runtime.prompt_group, "reason.md"),
            {
                "graph_yaml": write_graph_snapshot_reference(
                    container_manager,
                    container_name,
                    export_yaml.strip(),
                    phase="reason_execute",
                ),
                "fact_ids": format_fact_ids(allowed_fact_ids),
                "open_intents": format_open_intents(open_intents),
                "max_intents": str(config.tasks.reason.max_intents),
                "capability_instructions": capabilities.instructions,
                "role_instructions": role.instructions,
            },
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
            timeout_seconds=config.tasks.reason.timeout,
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
            reporter.emit_error("reason_execute", "error", f"command failed returncode={result.returncode}\n{result.stderr}")
            return outcome
        try:
            model_output = driver.extract_response_text(result.stdout, result.stderr)
            reporter.emit_result("reason_execute", model_output)
            payload = parse_json_output(model_output)
            kind, data = validate_reason_payload(
                payload, open_intents_empty=not open_intents, max_intents=config.tasks.reason.max_intents,
            )
        except Exception as exc:
            LOG.warning(
                "reason parse failed project=%s worker=%s error=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
                project.project.id,
                worker.name,
                exc,
                execute_ms,
                total_ms,
                preview(result.stdout),
                preview(result.stderr),
            )
            outcome = "failed"
            reporter.emit_error("reason_execute", "parse_error", str(exc))
            return outcome
        if kind == "rejected":
            LOG.warning(
                "reason rejected project=%s worker=%s execute_ms=%s total_ms=%s stdout_preview=%s",
                project.project.id,
                worker.name,
                execute_ms,
                total_ms,
                preview(result.stdout),
            )
            outcome = "rejected"
            reporter.emit_error("reason_execute", "error", "model rejected task")
            return outcome
        if kind == "complete":
            response = client.complete(project.project.id, data["from"], data["description"], worker.name)
            if response.status_code == 403:
                LOG.info("project became inactive during reason complete project=%s worker=%s", project.project.id, worker.name)
                outcome = "success"
                return outcome
            if not response.ok:
                LOG.warning(
                    "reason complete write failed project=%s worker=%s status=%s body=%s",
                    project.project.id,
                    worker.name,
                    response.status_code,
                    response.text,
                )
                outcome = "failed"
                reporter.emit_error("reason_execute", "error", f"complete write failed status={response.status_code} body={response.text}")
                return outcome
            LOG.info(
                "project completed project=%s worker=%s from=%s execute_ms=%s total_ms=%s",
                project.project.id,
                worker.name,
                data["from"],
                execute_ms,
                total_ms,
            )
            outcome = "success"
            reporter.emit_result("reason_write", data["description"], produced_fact_id="goal")
            return outcome
        if kind == "intents":
            created = 0
            created_ids: list[str] = []
            for intent_data in data:
                response = client.create_intent(project.project.id, intent_data["from"], intent_data["description"], worker.name)
                if response.status_code == 403:
                    LOG.info("project became inactive during reason intent create project=%s worker=%s created=%s", project.project.id, worker.name, created)
                    outcome = "success"
                    return outcome
                if response.status_code == 409:
                    LOG.info("reason intent lost race project=%s worker=%s from=%s", project.project.id, worker.name, intent_data["from"])
                    continue
                if not response.ok:
                    LOG.warning(
                        "reason intent write failed project=%s worker=%s status=%s body=%s",
                        project.project.id,
                        worker.name,
                        response.status_code,
                        response.text,
                    )
                    continue
                created += 1
                if isinstance(response.data, dict) and isinstance(response.data.get("id"), str):
                    created_ids.append(response.data["id"])
                LOG.info(
                    "reason created intent project=%s worker=%s from=%s description=%s",
                    project.project.id,
                    worker.name,
                    intent_data["from"],
                    intent_data["description"],
                )
            LOG.info(
                "reason finished project=%s worker=%s created_intents=%s/%s execute_ms=%s total_ms=%s",
                project.project.id,
                worker.name,
                created,
                len(data),
                execute_ms,
                total_ms,
            )
            if created == 0:
                LOG.warning(
                    "reason created no intents project=%s worker=%s attempted=%s execute_ms=%s total_ms=%s",
                    project.project.id,
                    worker.name,
                    len(data),
                    execute_ms,
                    total_ms,
                )
                outcome = "failed"
                reporter.emit_error("reason_write", "error", f"created no intents attempted={len(data)}")
                return outcome
            outcome = "success"
            reporter.emit_result("reason_write", f"created {created} intents", created_intent_ids=created_ids)
            return outcome
        LOG.info(
            "reason finished without graph change project=%s worker=%s execute_ms=%s total_ms=%s",
            project.project.id,
            worker.name,
            execute_ms,
            total_ms,
        )
        outcome = "success"
        return outcome
    finally:
        reporter.finish(process_state_for_task_outcome(outcome), error_kind=None if outcome == "success" else outcome)
        lease.stop()
        best_effort_release_reason(client, project.project.id, worker.name)


def _project_capability_data(
    client: CairnClient,
    project_id: str,
    reporter: ExecutionReporter,
    phase: str,
) -> dict | None:
    response = client.get_project_capabilities(project_id)
    if response.ok and isinstance(response.data, dict):
        return response.data
    reporter.emit_error(phase, "error", f"capability selection fetch failed status={response.status_code}")
    return None


def _project_role_data(
    client: CairnClient,
    project_id: str,
    reporter: ExecutionReporter,
    phase: str,
) -> dict | None:
    response = client.get_project_role(project_id)
    if response.ok and isinstance(response.data, dict):
        return response.data
    reporter.emit_error(phase, "error", f"project role fetch failed status={response.status_code}")
    return None
