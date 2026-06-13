from __future__ import annotations

from typing import Any

from cairn.dispatcher.protocol.base import HttpClientBase
from cairn.dispatcher.protocol.results import ApiResult


class ObservabilityApiClient(HttpClientBase):
    def create_llm_execution(
        self,
        project_id: str,
        execution_id: str,
        *,
        intent_id: str | None,
        task_type: str,
        worker: str,
    ) -> ApiResult:
        return self._request_observability_json(
            "POST",
            f"/projects/{project_id}/llm-executions",
            json={"id": execution_id, "intent_id": intent_id, "task_type": task_type, "worker": worker},
        )

    def create_llm_events(
        self,
        project_id: str,
        execution_id: str,
        events: list[dict[str, str]],
    ) -> ApiResult:
        return self._request_observability_json(
            "POST",
            f"/projects/{project_id}/llm-executions/{execution_id}/events/batch",
            json={"events": events},
        )

    def finish_llm_execution(
        self,
        project_id: str,
        execution_id: str,
        *,
        process_state: str,
        returncode: int | None = None,
        timed_out: bool = False,
        error_kind: str | None = None,
        produced_fact_id: str | None = None,
        created_intent_ids: list[str] | None = None,
    ) -> ApiResult:
        body: dict[str, Any] = {
            "process_state": process_state,
            "returncode": returncode,
            "timed_out": timed_out,
            "error_kind": error_kind,
            "produced_fact_id": produced_fact_id,
            "created_intent_ids": created_intent_ids,
        }
        return self._request_observability_json(
            "POST",
            f"/projects/{project_id}/llm-executions/{execution_id}/finish",
            json=body,
        )
