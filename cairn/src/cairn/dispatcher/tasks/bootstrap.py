from __future__ import annotations

import logging
from typing import Any
import time
from dataclasses import dataclass

from cairn.dispatcher.config import DispatchConfig, WorkerConfig
from cairn.dispatcher.capabilities import inject_project_capabilities
from cairn.dispatcher.roles import inject_project_role
from cairn.dispatcher.contracts import (
    parse_json_output,
    validate_bootstrap_conclude_payload,
    validate_bootstrap_execute_payload,
)
from cairn.dispatcher.observability.reporter import ExecutionReporter
from cairn.dispatcher.prompting import format_hints, format_remote_support_instructions, load_prompt, render_prompt
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.runtime.heartbeat import HeartbeatLease
from cairn.dispatcher.tasks.common import (
    best_effort_release,
    cancel_reason,
    did_timeout,
    project_allows_conclude_fallback,
    preview,
    process_state_for_task_outcome,
    run_healthcheck,
    run_worker_process,
    write_conclude_result_with_fact_id,
)
from cairn.dispatcher.workers.registry import get_driver
from cairn.server.models import Intent, ProjectDetail

LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class BootstrapCompleteWriteResult:
    status: str
    fact_id: str | None = None


def run_bootstrap_task(
    config: DispatchConfig,
    client: CairnClient,
    container_manager: ContainerManager,
    project: ProjectDetail,
    intent: Intent,
    worker: WorkerConfig,
    cancellation: TaskCancellation,
) -> str:
    driver = get_driver(worker.type)
    reporter = ExecutionReporter(
        client,
        config.observability,
        project_id=project.project.id,
        intent_id=intent.id,
        task_type="bootstrap",
        worker=worker.name,
    ) if config.observability.enabled else ExecutionReporter.disabled()
    reporter.start()
    outcome = "failed"
    task_started = time.perf_counter()
    healthcheck_timeout = config.runtime.healthcheck_timeout
    lease = HeartbeatLease.for_intent(client, project.project.id, intent.id, worker.name, config.runtime.interval)
    lease.start()
    try:
        container_name = container_manager.ensure_running(project.project.id)

        LOG.info(
            "starting container exec project=%s intent=%s worker=%s phase=bootstrap_healthcheck timeout=%ss",
            project.project.id,
            intent.id,
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
                "bootstrap cancelled during healthcheck project=%s intent=%s worker=%s reason=%s",
                project.project.id,
                intent.id,
                worker.name,
                cancelled,
            )
            best_effort_release(client, project.project.id, intent.id, worker.name)
            outcome = "cancelled"
            reporter.emit_error("bootstrap_healthcheck", "cancelled", cancelled)
            return outcome
        if lease.failure is not None:
            LOG.warning(
                "heartbeat lost during bootstrap healthcheck project=%s intent=%s worker=%s status=%s",
                project.project.id,
                intent.id,
                worker.name,
                lease.failure.status_code,
            )
            best_effort_release(client, project.project.id, intent.id, worker.name)
            outcome = "failed"
            reporter.emit_error("bootstrap_healthcheck", "error", f"heartbeat lost status={lease.failure.status_code}")
            return outcome
        if healthcheck.result.returncode != 0:
            LOG.warning(
                "worker unhealthy project=%s intent=%s worker=%s healthcheck_ms=%s stderr=%s",
                project.project.id,
                intent.id,
                worker.name,
                healthcheck.duration_ms,
                preview(healthcheck.result.stderr),
            )
            best_effort_release(client, project.project.id, intent.id, worker.name)
            outcome = "unhealthy"
            reporter.emit_error("bootstrap_healthcheck", "error", healthcheck.result.stderr)
            return outcome

        capability_data = _project_capability_data(client, project.project.id, reporter, "bootstrap_start")
        reporter.emit_capability_manifest(
            "bootstrap_start",
            _capability_manifest_payload(project.project.id, "bootstrap", capability_data),
        )

        capabilities = inject_project_capabilities(
            config,
            container_manager,
            container_name,
            project.project.id,
            "bootstrap",
            f"bootstrap-{intent.id}",
            capability_data,
        )
        if capabilities.summary:
            reporter.emit_result("capabilities", capabilities.summary)
        for error in capabilities.errors:
            reporter.emit_error("capabilities", "error", error)

        role = inject_project_role(
            project.project.id,
            "bootstrap",
            _project_role_data(client, project.project.id, reporter, "bootstrap"),
        )
        if role.summary:
            reporter.emit_result("role", role.summary)
        for error in role.errors or []:
            reporter.emit_error("role", "error", error)

        prompt = render_prompt(
            load_prompt(config.runtime.prompt_group, "bootstrap.md"),
            {
                **_bootstrap_prompt_replacements(project),
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
            timeout_seconds=config.tasks.bootstrap.timeout,
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
                outcome = _try_conclude_fallback(
                    config,
                    client,
                    container_manager,
                    container_name,
                    worker,
                    driver,
                    project,
                    intent,
                    session,
                    lease,
                    cancellation,
                    reporter,
                    capabilities.context,
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
            complete = _write_bootstrap_complete_result(
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
            outcome = _try_conclude_fallback(
                config,
                client,
                container_manager,
                container_name,
                worker,
                driver,
                project,
                intent,
                session,
                lease,
                cancellation,
                reporter,
                capabilities.context,
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
        reporter.finish(process_state_for_task_outcome(outcome), error_kind=None if outcome == "success" else outcome)
        lease.stop()


def _try_conclude_fallback(
    config: DispatchConfig,
    client: CairnClient,
    container_manager: ContainerManager,
    container_name: str,
    worker: WorkerConfig,
    driver,
    project: ProjectDetail,
    intent: Intent,
    session: str | None,
    lease: HeartbeatLease,
    cancellation: TaskCancellation,
    reporter: ExecutionReporter,
    capability_context=None,
) -> str:
    if not driver.supports_conclude() or not session:
        LOG.info(
            "bootstrap conclude fallback unavailable project=%s intent=%s worker=%s supports_conclude=%s has_session=%s",
            project.project.id,
            intent.id,
            worker.name,
            driver.supports_conclude(),
            bool(session),
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        reporter.emit_error("bootstrap_conclude", "error", "conclude fallback unavailable")
        return "failed"
    if lease.failure is not None:
        LOG.warning(
            "bootstrap conclude fallback skipped because heartbeat already lost project=%s intent=%s worker=%s",
            project.project.id,
            intent.id,
            worker.name,
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        reporter.emit_error("bootstrap_conclude", "error", f"heartbeat lost status={lease.failure.status_code}")
        return "failed"
    if cancellation.is_cancelled:
        LOG.info(
            "bootstrap conclude fallback skipped because task was cancelled project=%s intent=%s worker=%s reason=%s",
            project.project.id,
            intent.id,
            worker.name,
            cancellation.reason,
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        reporter.emit_error("bootstrap_conclude", "cancelled", cancellation.reason or "cancelled")
        return "cancelled"

    if not project_allows_conclude_fallback(
        client,
        project.project.id,
        worker_name=worker.name,
        intent_id=intent.id,
    ):
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"

    container_name = container_manager.ensure_running(project.project.id)

    prompt = render_prompt(
        load_prompt(config.runtime.prompt_group, "bootstrap_conclude.md"),
        _bootstrap_prompt_replacements(project),
    )
    reporter.emit_prompt("bootstrap_conclude", prompt)
    conclude_argv = driver.build_conclude(worker, prompt, session, capability_context)
    LOG.info("starting bootstrap conclude fallback project=%s intent=%s worker=%s", project.project.id, intent.id, worker.name)
    conclude_started = time.perf_counter()
    result = run_worker_process(
        container_manager,
        container_name,
        worker,
        conclude_argv,
        phase="bootstrap_conclude",
        timeout_seconds=config.tasks.bootstrap.conclude_timeout,
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
        payload = parse_json_output(model_output)
        conclude_data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if isinstance(conclude_data, dict) and isinstance(conclude_data.get("complete"), dict):
            LOG.warning(
                "bootstrap conclude returned unexpected complete payload project=%s intent=%s worker=%s complete_preview=%s",
                project.project.id,
                intent.id,
                worker.name,
                preview(str(conclude_data.get("complete"))),
            )
        kind, fact_description = validate_bootstrap_conclude_payload(payload)
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
    if kind == "rejected":
        LOG.warning(
            "bootstrap conclude rejected project=%s intent=%s worker=%s conclude_ms=%s stdout_preview=%s",
            project.project.id,
            intent.id,
            worker.name,
            conclude_ms,
            preview(result.stdout),
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        reporter.emit_error("bootstrap_conclude", "error", "model rejected task")
        return "rejected"
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


def _bootstrap_prompt_replacements(project: ProjectDetail) -> dict[str, str]:
    facts = {fact.id: fact.description for fact in project.facts}
    hints = [
        {
            "id": hint.id,
            "content": hint.content,
            "creator": hint.creator,
            "created_at": hint.created_at,
        }
        for hint in project.hints
    ]
    return {
        "origin": facts.get("origin", ""),
        "goal": facts.get("goal", ""),
        "hints": format_hints(hints),
    }


def _capability_manifest_payload(
    project_id: str,
    task_type: str,
    capability_data: dict[str, Any] | None,
) -> dict[str, Any]:
    if not capability_data:
        return {
            "summary": "Project capabilities before bootstrap: no capability selection available",
            "project_id": project_id,
            "task_type": task_type,
            "mcp_servers": [],
            "skills": [],
            "unavailable_mcp_server_ids": [],
            "unavailable_skill_ids": [],
        }

    selection = capability_data.get("selection") if isinstance(capability_data.get("selection"), dict) else {}
    catalog = capability_data.get("catalog") if isinstance(capability_data.get("catalog"), list) else []
    mcp_ids = _string_list(selection.get("mcp_server_ids"))
    skill_ids = _string_list(selection.get("skill_ids"))
    by_key = {
        (item.get("kind"), item.get("id")): item
        for item in catalog
        if isinstance(item, dict)
    }
    mcp_servers = [_manifest_item("mcp_server", capability_id, by_key, task_type) for capability_id in mcp_ids]
    skills = [_manifest_item("skill", capability_id, by_key, task_type) for capability_id in skill_ids]
    unavailable_mcp = _string_list(capability_data.get("unavailable_mcp_server_ids"))
    unavailable_skills = _string_list(capability_data.get("unavailable_skill_ids"))
    return {
        "summary": f"Project capabilities before bootstrap: {len(mcp_servers)} MCP servers, {len(skills)} skills",
        "project_id": project_id,
        "task_type": task_type,
        "mcp_servers": mcp_servers,
        "skills": skills,
        "unavailable_mcp_server_ids": unavailable_mcp,
        "unavailable_skill_ids": unavailable_skills,
    }


def _manifest_item(
    kind: str,
    capability_id: str,
    catalog: dict[tuple[Any, Any], dict[str, Any]],
    task_type: str,
) -> dict[str, Any]:
    item = catalog.get((kind, capability_id)) or {}
    task_types = _string_list(item.get("task_types"))
    return {
        "id": capability_id,
        "name": _string_value(item.get("name")) or capability_id,
        "detail": _string_value(item.get("detail")) or "",
        "task_types": task_types,
        "available": bool(item.get("available", False)),
        "enabled_for_task": task_type in task_types,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _string_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


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


def _write_bootstrap_complete_result(
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
