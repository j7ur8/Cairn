from __future__ import annotations

import logging
from dataclasses import dataclass

from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.tasks.task_release import best_effort_release

LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class ConcludeWriteResult:
    status: str
    fact_id: str | None = None


def write_conclude_result(
    client: CairnClient,
    project_id: str,
    intent_id: str,
    worker_name: str,
    description: str,
    *,
    source: str,
    phase_ms: int,
    total_ms: int | None = None,
) -> str:
    return write_conclude_result_with_fact_id(
        client,
        project_id,
        intent_id,
        worker_name,
        description,
        source=source,
        phase_ms=phase_ms,
        total_ms=total_ms,
    ).status


def write_conclude_result_with_fact_id(
    client: CairnClient,
    project_id: str,
    intent_id: str,
    worker_name: str,
    description: str,
    *,
    source: str,
    phase_ms: int,
    total_ms: int | None = None,
) -> ConcludeWriteResult:
    response = client.conclude(project_id, intent_id, worker_name, description)
    if response.ok:
        fact_id: str | None = None
        if isinstance(response.data, dict):
            fact = response.data.get("fact")
            if isinstance(fact, dict):
                candidate = fact.get("id")
                if isinstance(candidate, str) and candidate:
                    fact_id = candidate
        if total_ms is None:
            LOG.info(
                "intent concluded project=%s intent=%s worker=%s source=%s phase_ms=%s",
                project_id,
                intent_id,
                worker_name,
                source,
                phase_ms,
            )
        else:
            LOG.info(
                "intent concluded project=%s intent=%s worker=%s source=%s phase_ms=%s total_ms=%s",
                project_id,
                intent_id,
                worker_name,
                source,
                phase_ms,
                total_ms,
            )
        return ConcludeWriteResult(status="success", fact_id=fact_id)
    if response.status_code == 403:
        LOG.info(
            "project became inactive during conclude project=%s intent=%s worker=%s",
            project_id,
            intent_id,
            worker_name,
        )
    else:
        LOG.warning(
            "conclude write failed project=%s intent=%s worker=%s status=%s body=%s",
            project_id,
            intent_id,
            worker_name,
            response.status_code,
            response.text,
        )
    best_effort_release(client, project_id, intent_id, worker_name)
    return ConcludeWriteResult(status="failed", fact_id=None)
