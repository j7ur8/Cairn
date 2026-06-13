from __future__ import annotations

from dataclasses import dataclass

from cairn.dispatcher.observability.reporter import DisabledExecutionReporter, ExecutionReporter
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.heartbeat import HeartbeatLease
from cairn.dispatcher.tasks.task_outcome import process_state_for_task_outcome
from cairn.shared.config import DispatchConfig, WorkerConfig


@dataclass(slots=True)
class TaskRunContext:
    config: DispatchConfig
    client: CairnClient
    project_id: str
    task_type: str
    worker: WorkerConfig
    intent_id: str | None = None
    reason_run_id: str | None = None


class TaskLifecycle:
    def __init__(self, context: TaskRunContext) -> None:
        self.context = context
        self.reporter = self._build_reporter()
        self.lease = self._build_lease()

    def start(self) -> None:
        self.reporter.start()
        self.lease.start()

    def finish(self, outcome: str) -> None:
        self.reporter.finish(
            process_state_for_task_outcome(outcome),
            error_kind=None if outcome == "success" else outcome,
        )
        self.lease.stop()

    def _build_reporter(self) -> ExecutionReporter | DisabledExecutionReporter:
        config = self.context.config
        if not config.observability.enabled:
            return ExecutionReporter.disabled()
        return ExecutionReporter(
            self.context.client,
            config.observability,
            project_id=self.context.project_id,
            intent_id=self.context.intent_id,
            task_type=self.context.task_type,
            worker=self.context.worker.name,
        )

    def _build_lease(self) -> HeartbeatLease:
        context = self.context
        if context.task_type == "reason":
            assert context.reason_run_id is not None
            return HeartbeatLease.for_reason(
                context.client,
                context.project_id,
                context.worker.name,
                context.config.runtime.interval,
                context.reason_run_id,
            )
        assert context.intent_id is not None
        return HeartbeatLease.for_intent(
            context.client,
            context.project_id,
            context.intent_id,
            context.worker.name,
            context.config.runtime.interval,
        )
