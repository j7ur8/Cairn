from __future__ import annotations

import logging

from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.scheduler.log_state import LogState

LOG = logging.getLogger(__name__)


class ExecutionConfigResolver:
    def __init__(self, client: CairnClient, log_state: LogState) -> None:
        self.client = client
        self.log_state = log_state

    def get_task_execution_config(self, project_id: str, task_type: str) -> dict | None:
        response = self.client.get_project_execution_config(project_id, task_type)
        if response.ok and isinstance(response.data, dict):
            return response.data
        self.log_state.log_changed(
            LOG,
            f"project:{project_id}:execution-config:{task_type}",
            logging.WARNING,
            "execution config fetch failed project=%s task=%s status=%s",
            project_id,
            task_type,
            response.status_code,
        )
        return None
