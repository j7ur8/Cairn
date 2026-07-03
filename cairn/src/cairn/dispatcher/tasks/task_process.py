from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from cairn.dispatcher.observability.reporter import DisabledExecutionReporter, ExecutionReporter
from cairn.dispatcher.observability.trace import make_trace_parser
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.heartbeat import HeartbeatLease
from cairn.dispatcher.runtime.process import ProcessResult
from cairn.dispatcher.tasks.context import ContainerRuntime
from cairn.shared.config import WorkerConfig

HEALTHCHECK_COMMUNICATE_GRACE_SECONDS = 10
PROCESS_COMMUNICATE_GRACE_SECONDS = 15
LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class HealthcheckRun:
    result: ProcessResult
    duration_ms: int


def communicate_timeout(timeout_seconds: int, grace_seconds: int = PROCESS_COMMUNICATE_GRACE_SECONDS) -> int:
    return timeout_seconds + grace_seconds


def run_healthcheck(
    container_manager: ContainerRuntime,
    container_name: str,
    worker: WorkerConfig,
    command: list[str],
    *,
    timeout_seconds: int,
    tty: bool = False,
    lease: HeartbeatLease | None = None,
    cancellation: TaskCancellation | None = None,
) -> HealthcheckRun:
    process = container_manager.build_exec_process(
        container_name,
        _worker_exec_env(worker),
        command,
        timeout_seconds=timeout_seconds,
        tty=tty,
    )
    process.start()
    if lease is not None:
        lease.attach_process(process)
    if cancellation is not None:
        cancellation.attach_process(process)
    started = time.perf_counter()
    try:
        result = process.communicate(timeout=communicate_timeout(timeout_seconds, HEALTHCHECK_COMMUNICATE_GRACE_SECONDS))
    finally:
        if lease is not None:
            lease.attach_process(None)
        if cancellation is not None:
            cancellation.attach_process(None)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return HealthcheckRun(result=result, duration_ms=duration_ms)


def run_worker_process(
    container_manager: ContainerRuntime,
    container_name: str,
    worker: WorkerConfig,
    argv: list[str],
    *,
    phase: str,
    timeout_seconds: int,
    tty: bool = False,
    lease: HeartbeatLease | None = None,
    cancellation: TaskCancellation | None = None,
    reporter: ExecutionReporter | DisabledExecutionReporter | None = None,
    trace_format: str | None = None,
) -> ProcessResult:
    LOG.info(
        "starting container exec container=%s worker=%s phase=%s timeout=%ss",
        container_name,
        worker.name,
        phase,
        timeout_seconds,
    )
    trace_parser = make_trace_parser(trace_format, phase)

    def on_output(stream: str, chunk: str) -> None:
        if reporter is None:
            return
        if stream == "stdout" and trace_parser is not None:
            try:
                events = trace_parser.feed(chunk)
            except Exception as exc:
                LOG.debug("worker trace parse failed phase=%s format=%s error=%s", phase, trace_format, exc)
                events = []
                reporter.emit_error(phase, "trace_parse_error", str(exc))
            for event in events:
                reporter.emit_trace_event(event)
            settings = getattr(reporter, "settings", None)
            if settings is not None and settings.record_raw_worker_stream:
                reporter.emit_output(phase, stream, chunk)
            return
        reporter.emit_output(phase, stream, chunk)

    process = container_manager.build_exec_process(
        container_name,
        _worker_exec_env(worker),
        argv,
        timeout_seconds=timeout_seconds,
        tty=tty,
        on_output=on_output if reporter is not None else None,
    )
    process.start()
    if lease is not None:
        lease.attach_process(process)
    if cancellation is not None:
        cancellation.attach_process(process)
    try:
        result = process.communicate(timeout=communicate_timeout(timeout_seconds))
        if reporter is not None:
            if trace_parser is not None:
                try:
                    events = trace_parser.finish()
                except Exception as exc:
                    LOG.debug("worker trace parser finish failed phase=%s format=%s error=%s", phase, trace_format, exc)
                    events = []
                    reporter.emit_error(phase, "trace_parse_error", str(exc))
                for event in events:
                    reporter.emit_trace_event(event)
            reporter.flush()
        return result
    finally:
        if lease is not None:
            lease.attach_process(None)
        if cancellation is not None:
            cancellation.attach_process(None)


def _worker_exec_env(worker: WorkerConfig) -> dict[str, str]:
    return dict(worker.env)
