from __future__ import annotations

from cairn.dispatcher.observability.reporter import ExecutionReporter
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.runtime.heartbeat import HeartbeatLease
from cairn.dispatcher.tasks.task_process import run_worker_process
from cairn.shared.config import WorkerConfig


def run_task_process(
    container_manager: ContainerManager,
    container_name: str,
    worker: WorkerConfig,
    argv: list[str],
    *,
    phase: str,
    timeout: int,
    lease: HeartbeatLease,
    cancellation: TaskCancellation,
    reporter: ExecutionReporter,
    tty: bool = False,
    trace_format: str | None = None,
):
    return run_worker_process(
        container_manager,
        container_name,
        worker,
        argv,
        phase=phase,
        timeout_seconds=timeout,
        tty=tty,
        lease=lease,
        cancellation=cancellation,
        reporter=reporter,
        trace_format=trace_format,
    )
