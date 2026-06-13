from __future__ import annotations

import logging

from cairn.dispatcher.observability.reporter import AnyReporter
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.runtime.heartbeat import HeartbeatLease
from cairn.dispatcher.tasks.task_outcome import cancel_reason
from cairn.dispatcher.tasks.task_process import run_healthcheck
from cairn.dispatcher.tasks.task_release import best_effort_release
from cairn.dispatcher.tasks.task_text import preview
from cairn.shared.config import WorkerConfig

LOG = logging.getLogger(__name__)


def run_intent_healthcheck_gate(
    *,
    task_type: str,
    client: CairnClient,
    container_manager: ContainerManager,
    container_name: str,
    project_id: str,
    intent_id: str,
    worker: WorkerConfig,
    command: list[str],
    timeout_seconds: int,
    tty: bool,
    lease: HeartbeatLease,
    cancellation: TaskCancellation,
    reporter: AnyReporter,
) -> str | None:
    phase = f"{task_type}_healthcheck"
    LOG.info(
        "starting container exec project=%s intent=%s worker=%s phase=%s timeout=%ss",
        project_id,
        intent_id,
        worker.name,
        phase,
        timeout_seconds,
    )
    healthcheck = run_healthcheck(
        container_manager,
        container_name,
        worker,
        command,
        timeout_seconds=timeout_seconds,
        tty=tty,
        lease=lease,
        cancellation=cancellation,
    )
    cancelled = cancel_reason(healthcheck.result, cancellation)
    if cancelled is not None:
        LOG.info(
            "%s cancelled during healthcheck project=%s intent=%s worker=%s reason=%s",
            task_type,
            project_id,
            intent_id,
            worker.name,
            cancelled,
        )
        best_effort_release(client, project_id, intent_id, worker.name)
        reporter.emit_error(phase, "cancelled", cancelled)
        return "cancelled"
    if lease.failure is not None:
        LOG.warning(
            "heartbeat lost during %s healthcheck project=%s intent=%s worker=%s status=%s",
            task_type,
            project_id,
            intent_id,
            worker.name,
            lease.failure.status_code,
        )
        best_effort_release(client, project_id, intent_id, worker.name)
        reporter.emit_error(phase, "error", f"heartbeat lost status={lease.failure.status_code}")
        return "failed"
    if healthcheck.result.returncode != 0:
        LOG.warning(
            "worker unhealthy project=%s intent=%s worker=%s healthcheck_ms=%s stderr=%s",
            project_id,
            intent_id,
            worker.name,
            healthcheck.duration_ms,
            preview(healthcheck.result.stderr),
        )
        best_effort_release(client, project_id, intent_id, worker.name)
        reporter.emit_error(phase, "error", healthcheck.result.stderr)
        return "unhealthy"
    return None
