from __future__ import annotations

import copy
import logging

from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.scheduler.log_state import LogState

LOG = logging.getLogger(__name__)


class ExecutionConfigResolver:
    def __init__(self, client: CairnClient, log_state: LogState) -> None:
        self.client = client
        self.log_state = log_state
        self._cache: dict[tuple[str, str], dict] = {}

    def get_task_execution_config(self, project_id: str, task_type: str) -> dict | None:
        key = (project_id, task_type)
        cached = self._cache.get(key)
        if cached is not None:
            return copy.deepcopy(cached)
        response = self.client.get_project_execution_config(project_id, task_type)
        if response.ok and isinstance(response.data, dict):
            self._cache[key] = copy.deepcopy(response.data)
            return copy.deepcopy(self._cache[key])
        if response.status_code == 404:
            self.clear_project(project_id)
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

    def clear_project(self, project_id: str) -> None:
        self._cache = {key: value for key, value in self._cache.items() if key[0] != project_id}

    def clear_all(self) -> None:
        self._cache.clear()
