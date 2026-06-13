from __future__ import annotations

import logging

from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.scheduler.log_state import LogState

LOG = logging.getLogger(__name__)


class ReplayCoordinator:
    def __init__(self, client: CairnClient, log_state: LogState) -> None:
        self.client = client
        self.log_state = log_state

    def advance_project(self, project_id: str) -> bool | None:
        response = self.client.advance_replay_run(project_id)
        if response.status_code == 404:
            return None
        if not response.ok:
            self.log_state.log_changed(
                LOG,
                f"project:{project_id}:replay_advance_error",
                logging.WARNING,
                "replay advance failed project=%s status=%s body=%s",
                project_id,
                response.status_code,
                response.text,
            )
            return False
        data = response.data
        if not isinstance(data, dict) or not data.get("is_replay"):
            return None
        action = str(data.get("action") or "")
        if action == "created_intent":
            self.log_state.clear_project(project_id)
            LOG.info("advanced replay project=%s created_intent=%s", project_id, data.get("intent_id"))
            return True
        if action == "completed":
            self.log_state.clear_project(project_id)
            LOG.info("advanced replay project=%s completed", project_id)
            return True
        if action == "blocked":
            self.log_state.log_changed(
                LOG,
                f"project:{project_id}:replay_blocked",
                logging.WARNING,
                "replay project blocked project=%s detail=%s",
                project_id,
                data.get("detail") or "",
            )
            return False
        if action == "waiting":
            return None
        self.log_state.log_changed(
            LOG,
            f"project:{project_id}:replay_waiting",
            logging.DEBUG,
            "replay project waiting project=%s action=%s intent=%s",
            project_id,
            action,
            data.get("intent_id"),
        )
        return False
