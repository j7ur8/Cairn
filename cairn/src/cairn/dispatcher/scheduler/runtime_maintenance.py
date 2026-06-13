from __future__ import annotations

import logging

from cairn.dispatcher.scheduler.cleanup import ContainerCleanupCoordinator
from cairn.dispatcher.scheduler.runtime_state import RuntimeTaskRegistry
from cairn.shared.contracts import ProjectSummary

LOG = logging.getLogger(__name__)


class RuntimeMaintenance:
    def __init__(
        self,
        *,
        runtime: RuntimeTaskRegistry,
        cleanup: ContainerCleanupCoordinator,
        clear_project_log_state,
    ) -> None:
        self.runtime = runtime
        self.cleanup = cleanup
        self.clear_project_log_state = clear_project_log_state

    def reap_futures(self) -> None:
        for task, outcome, error in self.runtime.reap_done():
            if error is not None:
                LOG.error(
                    "task crashed project=%s task=%s worker=%s",
                    task.project_id,
                    task.task_type,
                    task.worker_name,
                    exc_info=(type(error), error, error.__traceback__),
                )
                continue
            assert outcome is not None
            if outcome == "cancelled":
                LOG.info(
                    "task cancelled project=%s task=%s worker=%s",
                    task.project_id,
                    task.task_type,
                    task.worker_name,
                )
            elif outcome != "success":
                LOG.warning(
                    "task finished project=%s task=%s worker=%s outcome=%s",
                    task.project_id,
                    task.task_type,
                    task.worker_name,
                    outcome,
                )
            self.clear_project_log_state(task.project_id)
            self.runtime.record_task_outcome(task, outcome)

    def reap_cleanup_futures(self) -> None:
        self.cleanup.reap()

    def refresh_runtime_projects(self, summaries: list[ProjectSummary]) -> None:
        self.runtime.refresh_projects(summaries)
        self.cleanup.refresh_active_projects(summaries)

    def cancel_inactive_tasks(self, summaries: list[ProjectSummary]) -> None:
        self.runtime.cancel_inactive_tasks(summaries)

    def initialize_reason_checkpoints(self, summaries: list[ProjectSummary]) -> None:
        self.runtime.initialize_reason_checkpoints(summaries)
