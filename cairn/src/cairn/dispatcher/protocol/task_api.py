from __future__ import annotations

from cairn.dispatcher.protocol.base import HttpClientBase
from cairn.dispatcher.protocol.results import ApiResult


class TaskApiClient(HttpClientBase):
    def heartbeat(self, project_id: str, intent_id: str, worker: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/intents/{intent_id}/heartbeat",
            json={"worker": worker},
        )

    def claim(self, project_id: str, intent_id: str, worker: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/intents/{intent_id}/claim",
            json={"worker": worker},
        )

    def claim_reason(
        self,
        project_id: str,
        worker: str,
        trigger: str,
        *,
        run_id: str,
        trigger_hash: str,
        fact_count: int,
        hint_count: int,
        open_intent_count: int,
    ) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/reason/claim",
            json={
                "worker": worker,
                "run_id": run_id,
                "trigger": trigger,
                "trigger_hash": trigger_hash,
                "fact_count": fact_count,
                "hint_count": hint_count,
                "open_intent_count": open_intent_count,
            },
        )

    def finish_reason(
        self,
        project_id: str,
        worker: str,
        *,
        run_id: str,
        trigger: str,
        trigger_hash: str,
        fact_count: int,
        hint_count: int,
        open_intent_count: int,
        outcome: str,
        error: str | None = None,
    ) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/reason/finish",
            json={
                "worker": worker,
                "run_id": run_id,
                "trigger": trigger,
                "trigger_hash": trigger_hash,
                "fact_count": fact_count,
                "hint_count": hint_count,
                "open_intent_count": open_intent_count,
                "outcome": outcome,
                "error": error,
            },
        )

    def reason_heartbeat(self, project_id: str, worker: str, run_id: str | None = None) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/reason/heartbeat",
            json={"worker": worker, "run_id": run_id},
        )

    def release_reason(self, project_id: str, worker: str, run_id: str | None = None) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/reason/release",
            json={"worker": worker, "run_id": run_id},
        )

    def release(self, project_id: str, intent_id: str, worker: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/intents/{intent_id}/release",
            json={"worker": worker},
        )

    def conclude(self, project_id: str, intent_id: str, worker: str, description: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/intents/{intent_id}/conclude",
            json={"worker": worker, "description": description},
        )

    def complete(self, project_id: str, from_ids: list[str], description: str, worker: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/complete",
            json={"from": from_ids, "description": description, "worker": worker},
        )

    def create_intent(
        self,
        project_id: str,
        from_ids: list[str],
        description: str,
        creator: str,
        *,
        priority_score: float | None = None,
        intent_kind: str | None = None,
        tags: list[str] | None = None,
        score_reason: str | None = None,
        branch_key: str | None = None,
        branch_depth: int = 0,
        expected_value: float | None = None,
    ) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/intents",
            json={
                "from": from_ids,
                "description": description,
                "creator": creator,
                "worker": None,
                "priority_score": priority_score,
                "intent_kind": intent_kind,
                "tags": tags or [],
                "score_reason": score_reason,
                "branch_key": branch_key,
                "branch_depth": branch_depth,
                "expected_value": expected_value,
            },
        )

    def advance_replay_run(self, project_id: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/replay-runs/advance",
            json={},
        )
