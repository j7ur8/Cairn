from __future__ import annotations

import logging
import time
from concurrent.futures import Future

from cairn.dispatcher.models import ReasonCheckpoint, RunningTask
from cairn.shared.contracts import ProjectSummary
from cairn.shared.observability.metrics import WORKER_UNHEALTHY_SINCE

LOG = logging.getLogger(__name__)
UNHEALTHY_RETRY_AFTER_SECONDS = 5
REJECTED_RETRY_AFTER_SECONDS = 5


class RuntimeTaskRegistry:
    """Owns in-process task state for the dispatcher.

    The server remains the source of truth for project/intent leases. This
    registry tracks only local futures, local per-worker backoff, and local
    reason checkpoints used to avoid redundant reason tasks.
    """

    def __init__(self) -> None:
        self.futures: dict[Future[str], RunningTask] = {}
        self.project_ids: set[str] = set()
        self.worker_unhealthy_until: dict[str, float] = {}
        self.worker_rejected_until: dict[tuple[str, str, str], float] = {}
        self.reason_checkpoints: dict[str, ReasonCheckpoint] = {}

    def clear_backoff(self) -> None:
        self.worker_unhealthy_until.clear()
        self.worker_rejected_until.clear()

    def add(self, future: Future[str], task: RunningTask) -> None:
        self.futures[future] = task
        self.project_ids.add(task.project_id)

    def running_count(self) -> int:
        return len(self.futures)

    def worker_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for task in self.futures.values():
            counts[task.worker_name] = counts.get(task.worker_name, 0) + 1
        return counts

    def project_task_count(self, project_id: str) -> int:
        return sum(1 for task in self.futures.values() if task.project_id == project_id)

    def project_task_summary(self, project_id: str) -> list[str]:
        summary: list[str] = []
        for task in self.futures.values():
            if task.project_id != project_id:
                continue
            if task.intent_id is None:
                summary.append(f"{task.task_type}:{task.worker_name}")
            else:
                summary.append(f"{task.task_type}:{task.worker_name}:{task.intent_id}")
        summary.sort()
        return summary

    def has_running_bootstrap(self, project_id: str) -> bool:
        return any(task.project_id == project_id and task.task_type == "bootstrap" for task in self.futures.values())

    def running_explore_intents(self, project_id: str) -> set[str]:
        return {
            task.intent_id
            for task in self.futures.values()
            if task.project_id == project_id and task.task_type == "explore" and task.intent_id is not None
        }

    def running_project_count(self, summaries: list[ProjectSummary]) -> int:
        active_ids = {summary.id for summary in summaries if summary.status == "active"}
        return len(self.project_ids & active_ids)

    def refresh_projects(self, summaries: list[ProjectSummary]) -> None:
        active_ids = {summary.id for summary in summaries if summary.status == "active"}
        self.project_ids.intersection_update(active_ids)

    def cancel_inactive_tasks(self, summaries: list[ProjectSummary]) -> None:
        status_by_project = {summary.id: summary.status for summary in summaries}
        for task in self.futures.values():
            status = status_by_project.get(task.project_id, "deleted")
            if status != "active" and task.cancellation.cancel(status):
                LOG.info(
                    "cancelling running task for inactive project project=%s task=%s worker=%s status=%s",
                    task.project_id,
                    task.task_type,
                    task.worker_name,
                    status,
                )

    def initialize_reason_checkpoints(self, summaries: list[ProjectSummary]) -> None:
        for summary in summaries:
            if summary.status != "active":
                continue
            if summary.id in self.reason_checkpoints:
                continue
            open_intent_count = summary.working_intent_count + summary.unclaimed_intent_count
            if open_intent_count == 0:
                continue
            self.reason_checkpoints[summary.id] = ReasonCheckpoint(
                fact_count=summary.fact_count,
                hint_count=summary.hint_count,
                open_intent_count=open_intent_count,
            )
            LOG.debug(
                "reason checkpoint initialized project=%s facts=%s hints=%s open_intents=%s",
                summary.id,
                summary.fact_count,
                summary.hint_count,
                open_intent_count,
            )

    def reap_done(self) -> list[tuple[RunningTask, str | None, BaseException | None]]:
        done = [future for future in self.futures if future.done()]
        results: list[tuple[RunningTask, str | None, BaseException | None]] = []
        for future in done:
            task = self.futures.pop(future)
            try:
                results.append((task, future.result(), None))
            except BaseException as exc:  # noqa: BLE001 - logged by caller.
                results.append((task, None, exc))
        return results

    def record_task_outcome(self, task: RunningTask, outcome: str) -> None:
        if outcome == "unhealthy":
            retry_after_seconds = UNHEALTHY_RETRY_AFTER_SECONDS
            self.worker_unhealthy_until[task.worker_name] = time.time() + retry_after_seconds
            WORKER_UNHEALTHY_SINCE.labels(worker=task.worker_name).set(time.time())
            LOG.info(
                "worker marked unhealthy worker=%s retry_after=%.0fs",
                task.worker_name,
                retry_after_seconds,
            )
        else:
            self.worker_unhealthy_until.pop(task.worker_name, None)
            WORKER_UNHEALTHY_SINCE.labels(worker=task.worker_name).set(0)

        rejection_key = (task.project_id, task.task_type, task.worker_name)
        if outcome == "rejected":
            retry_after_seconds = REJECTED_RETRY_AFTER_SECONDS
            self.worker_rejected_until[rejection_key] = time.time() + retry_after_seconds
            LOG.info(
                "worker marked rejected project=%s task=%s worker=%s retry_after=%.0fs",
                task.project_id,
                task.task_type,
                task.worker_name,
                retry_after_seconds,
            )
        else:
            self.worker_rejected_until.pop(rejection_key, None)

        if outcome == "success" and task.task_type == "reason":
            assert task.fact_count is not None
            assert task.hint_count is not None
            assert task.open_intent_count is not None
            self.reason_checkpoints[task.project_id] = ReasonCheckpoint(
                fact_count=task.fact_count,
                hint_count=task.hint_count,
                open_intent_count=task.open_intent_count,
            )
            LOG.debug(
                "reason checkpoint updated project=%s facts=%s hints=%s open_intents=%s",
                task.project_id,
                task.fact_count,
                task.hint_count,
                task.open_intent_count,
            )
