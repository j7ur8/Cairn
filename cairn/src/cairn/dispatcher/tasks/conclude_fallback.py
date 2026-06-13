from __future__ import annotations

import logging

from cairn.dispatcher.observability.reporter import ExecutionReporter
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.heartbeat import HeartbeatLease
from cairn.dispatcher.tasks.task_release import best_effort_release, project_allows_conclude_fallback

LOG = logging.getLogger(__name__)


class ConcludeFallbackRunner:
    def __init__(
        self,
        *,
        client: CairnClient,
        project_id: str,
        intent_id: str,
        worker_name: str,
        phase: str,
        lease: HeartbeatLease,
        cancellation: TaskCancellation,
        reporter: ExecutionReporter,
    ) -> None:
        self.client = client
        self.project_id = project_id
        self.intent_id = intent_id
        self.worker_name = worker_name
        self.phase = phase
        self.lease = lease
        self.cancellation = cancellation
        self.reporter = reporter

    def preflight(self, *, supports_conclude: bool, has_session: bool) -> str | None:
        if not supports_conclude or not has_session:
            LOG.info(
                "%s fallback unavailable project=%s intent=%s worker=%s supports_conclude=%s has_session=%s",
                self.phase,
                self.project_id,
                self.intent_id,
                self.worker_name,
                supports_conclude,
                has_session,
            )
            best_effort_release(self.client, self.project_id, self.intent_id, self.worker_name)
            self.reporter.emit_error(self.phase, "error", "conclude fallback unavailable")
            return "failed"
        if self.lease.failure is not None:
            LOG.warning(
                "%s fallback skipped because heartbeat already lost project=%s intent=%s worker=%s",
                self.phase,
                self.project_id,
                self.intent_id,
                self.worker_name,
            )
            best_effort_release(self.client, self.project_id, self.intent_id, self.worker_name)
            self.reporter.emit_error(self.phase, "error", f"heartbeat lost status={self.lease.failure.status_code}")
            return "failed"
        if self.cancellation.is_cancelled:
            LOG.info(
                "%s fallback skipped because task was cancelled project=%s intent=%s worker=%s reason=%s",
                self.phase,
                self.project_id,
                self.intent_id,
                self.worker_name,
                self.cancellation.reason,
            )
            best_effort_release(self.client, self.project_id, self.intent_id, self.worker_name)
            self.reporter.emit_error(self.phase, "cancelled", self.cancellation.reason or "cancelled")
            return "cancelled"
        if not project_allows_conclude_fallback(
            self.client,
            self.project_id,
            worker_name=self.worker_name,
            intent_id=self.intent_id,
        ):
            best_effort_release(self.client, self.project_id, self.intent_id, self.worker_name)
            return "failed"
        return None
