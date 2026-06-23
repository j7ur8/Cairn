from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from cairn.dispatcher.contracts import parse_reason_output, validate_reason_payload
from cairn.dispatcher.observability.reporter import DisabledExecutionReporter, ExecutionReporter
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.process import ProcessResult
from cairn.dispatcher.tasks.task_text import preview

LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class ReasonStepResult:
    outcome: str
    finish_outcome: str
    finish_error: str | None = None


def apply_reason_result(
    *,
    client: CairnClient,
    driver: Any,
    project_id: str,
    worker_name: str,
    result: ProcessResult,
    open_intents: list[dict[str, object]],
    max_intents: int,
    execute_ms: int,
    total_ms: int,
    reporter: ExecutionReporter | DisabledExecutionReporter,
) -> ReasonStepResult:
    try:
        model_output = driver.extract_response_text(result.stdout, result.stderr)
        reporter.emit_result("reason_execute", model_output)
        payload = parse_reason_output(model_output)
        kind, data = validate_reason_payload(
            payload,
            open_intents_empty=not open_intents,
            max_intents=max_intents,
        )
    except Exception as exc:
        LOG.warning(
            "reason parse failed project=%s worker=%s error=%s execute_ms=%s total_ms=%s stdout_preview=%s stderr_preview=%s",
            project_id,
            worker_name,
            exc,
            execute_ms,
            total_ms,
            preview(result.stdout),
            preview(result.stderr),
        )
        reporter.emit_error("reason_execute", "parse_error", str(exc))
        return ReasonStepResult("failed", "failed", str(exc))

    if kind == "rejected":
        LOG.warning(
            "reason rejected project=%s worker=%s execute_ms=%s total_ms=%s stdout_preview=%s",
            project_id,
            worker_name,
            execute_ms,
            total_ms,
            preview(result.stdout),
        )
        reporter.emit_error("reason_execute", "error", "model rejected task")
        return ReasonStepResult("rejected", "rejected", "model rejected task")
    if kind == "complete":
        assert isinstance(data, dict)
        return _complete_project(
            client=client,
            project_id=project_id,
            worker_name=worker_name,
            data=data,
            execute_ms=execute_ms,
            total_ms=total_ms,
            reporter=reporter,
        )
    if kind == "intents":
        assert isinstance(data, list)
        return _create_intents(
            client=client,
            project_id=project_id,
            worker_name=worker_name,
            data=data,
            execute_ms=execute_ms,
            total_ms=total_ms,
            reporter=reporter,
        )
    LOG.info(
        "reason finished without graph change project=%s worker=%s execute_ms=%s total_ms=%s",
        project_id,
        worker_name,
        execute_ms,
        total_ms,
    )
    return ReasonStepResult("success", "noop")


def _complete_project(
    *,
    client: CairnClient,
    project_id: str,
    worker_name: str,
    data: dict[str, Any],
    execute_ms: int,
    total_ms: int,
    reporter: ExecutionReporter | DisabledExecutionReporter,
) -> ReasonStepResult:
    response = client.complete(project_id, data["from"], data["description"], worker_name)
    if response.status_code == 403:
        LOG.info("project became inactive during reason complete project=%s worker=%s", project_id, worker_name)
        return ReasonStepResult("success", "complete")
    if not response.ok:
        LOG.warning(
            "reason complete write failed project=%s worker=%s status=%s body=%s",
            project_id,
            worker_name,
            response.status_code,
            response.text,
        )
        reporter.emit_error(
            "reason_execute",
            "error",
            f"complete write failed status={response.status_code} body={response.text}",
        )
        return ReasonStepResult("failed", "failed", f"complete write failed status={response.status_code}")
    LOG.info(
        "project completed project=%s worker=%s from=%s execute_ms=%s total_ms=%s",
        project_id,
        worker_name,
        data["from"],
        execute_ms,
        total_ms,
    )
    reporter.emit_result("reason_write", data["description"], produced_fact_id="goal")
    return ReasonStepResult("success", "complete")


def _create_intents(
    *,
    client: CairnClient,
    project_id: str,
    worker_name: str,
    data: list[dict[str, Any]],
    execute_ms: int,
    total_ms: int,
    reporter: ExecutionReporter | DisabledExecutionReporter,
) -> ReasonStepResult:
    created = 0
    created_ids: list[str] = []
    for intent_data in data:
        response = client.create_intent(project_id, intent_data["from"], intent_data["description"], worker_name)
        if response.status_code == 403:
            LOG.info(
                "project became inactive during reason intent create project=%s worker=%s created=%s",
                project_id,
                worker_name,
                created,
            )
            return ReasonStepResult("success", "intents" if created else "noop")
        if response.status_code == 409:
            LOG.info("reason intent lost race project=%s worker=%s from=%s", project_id, worker_name, intent_data["from"])
            continue
        if not response.ok:
            LOG.warning(
                "reason intent write failed project=%s worker=%s status=%s body=%s",
                project_id,
                worker_name,
                response.status_code,
                response.text,
            )
            continue
        created += 1
        if isinstance(response.data, dict) and isinstance(response.data.get("id"), str):
            created_ids.append(response.data["id"])
        LOG.info(
            "reason created intent project=%s worker=%s from=%s description=%s",
            project_id,
            worker_name,
            intent_data["from"],
            intent_data["description"],
        )
    LOG.info(
        "reason finished project=%s worker=%s created_intents=%s/%s execute_ms=%s total_ms=%s",
        project_id,
        worker_name,
        created,
        len(data),
        execute_ms,
        total_ms,
    )
    if created == 0:
        LOG.warning(
            "reason created no intents project=%s worker=%s attempted=%s execute_ms=%s total_ms=%s",
            project_id,
            worker_name,
            len(data),
            execute_ms,
            total_ms,
        )
        reporter.emit_error("reason_write", "error", f"created no intents attempted={len(data)}")
        return ReasonStepResult("failed", "failed", f"created no intents attempted={len(data)}")
    reporter.emit_result(
        "reason_write",
        f"created {created} intents",
        created_intent_ids=created_ids,
    )
    return ReasonStepResult("success", "intents")
