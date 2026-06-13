from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future

from cairn.dispatcher.models import RunningTask
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.scheduler.log_state import LogState
from cairn.dispatcher.scheduler.runtime_state import RuntimeTaskRegistry

LOG = logging.getLogger(__name__)


class TaskSubmissionRegistry:
    def __init__(self, *, runtime: RuntimeTaskRegistry, log_state: LogState) -> None:
        self.runtime = runtime
        self.log_state = log_state

    def refresh(self, *, runtime: RuntimeTaskRegistry) -> None:
        self.runtime = runtime

    def submit_and_register(
        self,
        *,
        task_type: str,
        project_id: str,
        worker_name: str,
        intent_id: str | None,
        release: Callable[[], None],
        submit: Callable[[TaskCancellation], Future[str]],
        running_task: Callable[[TaskCancellation], RunningTask],
        success_log: Callable[[], None],
    ) -> bool:
        try:
            cancellation = TaskCancellation()
            future = submit(cancellation)
        except Exception:
            if intent_id is None:
                LOG.exception("failed to submit %s task project=%s worker=%s", task_type, project_id, worker_name)
            else:
                LOG.exception(
                    "failed to submit %s task project=%s intent=%s worker=%s",
                    task_type,
                    project_id,
                    intent_id,
                    worker_name,
                )
            release()
            return False
        self.runtime.add(future, running_task(cancellation))
        self.log_state.clear_project(project_id)
        success_log()
        return True
