from __future__ import annotations

import logging
from collections.abc import Callable

from cairn.dispatcher.protocol.client import CairnClient
from cairn.shared.contracts import Intent

LOG = logging.getLogger(__name__)


class TaskClaimer:
    def __init__(
        self,
        *,
        client: CairnClient,
        release_intent: Callable[[str, str, str], None],
        release_reason: Callable[[str, str, str | None], None],
    ) -> None:
        self.client = client
        self.release_intent = release_intent
        self.release_reason = release_reason

    def refresh(self, *, client: CairnClient) -> None:
        self.client = client

    def claim_intent(self, *, task_type: str, project_id: str, intent: Intent, worker_name: str) -> bool:
        claim = self.client.claim(project_id, intent.id, worker_name)
        if claim.status_code in (403, 409):
            level = logging.INFO if claim.status_code == 403 else logging.WARNING
            LOG.log(
                level,
                "%s claim failed project=%s intent=%s worker=%s status=%s",
                task_type,
                project_id,
                intent.id,
                worker_name,
                claim.status_code,
            )
            return False
        if not claim.ok:
            LOG.warning(
                "%s claim failed project=%s intent=%s worker=%s status=%s",
                task_type,
                project_id,
                intent.id,
                worker_name,
                claim.status_code,
            )
            return False
        return True

    def claim_reason(
        self,
        *,
        project_id: str,
        worker_name: str,
        trigger: str,
        run_id: str,
        trigger_hash: str,
        fact_count: int,
        hint_count: int,
        open_intent_count: int,
    ) -> bool:
        claim = self.client.claim_reason(
            project_id,
            worker_name,
            trigger,
            run_id=run_id,
            trigger_hash=trigger_hash,
            fact_count=fact_count,
            hint_count=hint_count,
            open_intent_count=open_intent_count,
        )
        if claim.status_code in (403, 409):
            level = logging.INFO if claim.status_code == 403 else logging.WARNING
            LOG.log(level, "reason claim failed project=%s worker=%s status=%s", project_id, worker_name, claim.status_code)
            return False
        if not claim.ok:
            LOG.warning("reason claim failed project=%s worker=%s status=%s", project_id, worker_name, claim.status_code)
            return False
        return True

    def release_claim(self, *, project_id: str, intent_id: str | None, worker_name: str, run_id: str | None) -> None:
        if intent_id is None:
            self.release_reason(project_id, worker_name, run_id)
            return
        self.release_intent(project_id, intent_id, worker_name)
