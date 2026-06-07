"""Worker selection logic, isolated from the scheduler loop.

The scheduler loop is responsible for orchestrating ticks; the
worker selection code is a self-contained decision: "given the
current worker pool, the task type, and the unhealthy / rejected
backoff state, which worker (if any) should run this task?". Pulling
it out of the loop class makes the decision unit-testable without
spinning up the full scheduler, and makes the loop's
``_select_worker_default`` a thin delegation.

The AI-chain path (``_select_worker_for_ai_chain``) is intentionally
left in the loop because it interleaves a probe + env overlay
merge that are tightly coupled to the running task state. The pure
selection kernel (``select_worker_default``) is the same kernel
that path delegates to, so this module is the canonical home for
"is worker X runnable for project/task right now?".
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from cairn.dispatcher.config import WorkerConfig
from cairn.dispatcher.scheduler.worker_select import choose_worker

LOG = logging.getLogger(__name__)


@dataclass(slots=True)
class WorkerSelection:
    """Result of a worker selection pass.

    ``worker`` is ``None`` when no candidate cleared the backoff /
    capacity gates. The ``blocked_*`` lists capture *why* each
    candidate was rejected so a follow-up debug log can show the
    operator the full picture.
    """

    worker: WorkerConfig | None
    blocked_busy: list[str]
    blocked_unhealthy: list[str]
    blocked_rejected: list[str]
    blocked_task_type: list[str]


def select_worker_default(
    *,
    project_id: str,
    task_type: str,
    workers: list[WorkerConfig],
    running_counts: dict[str, int],
    worker_unhealthy_until: dict[str, float],
    worker_rejected_until: dict[tuple[str, str, str], float],
    now: float | None = None,
) -> WorkerSelection:
    """Pick the highest-priority worker that fits ``task_type``.

    Returns a :class:`WorkerSelection` with ``worker=None`` if no
    candidate clears the gates. ``now`` defaults to ``time.time()``;
    tests pass an explicit value to keep the result deterministic.
    """
    if now is None:
        now = time.time()
    candidates: list[WorkerConfig] = []
    blocked_busy: list[str] = []
    blocked_unhealthy: list[str] = []
    blocked_rejected: list[str] = []
    blocked_task_type: list[str] = []
    for worker in workers:
        if task_type not in worker.task_types:
            blocked_task_type.append(worker.name)
            continue
        running = running_counts.get(worker.name, 0)
        if running >= worker.max_running:
            blocked_busy.append(f"{worker.name}({running}/{worker.max_running})")
            continue
        unhealthy_until = worker_unhealthy_until.get(worker.name, 0)
        if unhealthy_until > now:
            blocked_unhealthy.append(f"{worker.name}({unhealthy_until - now:.1f}s)")
            continue
        rejected_until = worker_rejected_until.get((project_id, task_type, worker.name), 0)
        if rejected_until > now:
            blocked_rejected.append(f"{worker.name}({rejected_until - now:.1f}s)")
            continue
        candidates.append(worker)
    if not candidates:
        LOG.debug(
            "worker selection project=%s task=%s no candidates blocked_busy=%s blocked_unhealthy=%s blocked_rejected=%s blocked_task_type=%s",
            project_id, task_type, blocked_busy, blocked_unhealthy, blocked_rejected, blocked_task_type,
        )
        return WorkerSelection(
            worker=None,
            blocked_busy=blocked_busy,
            blocked_unhealthy=blocked_unhealthy,
            blocked_rejected=blocked_rejected,
            blocked_task_type=blocked_task_type,
        )
    ordered = choose_worker(candidates, running_counts)
    chosen = ordered[0] if ordered else None
    LOG.debug(
        "worker selection project=%s task=%s candidates=%s chosen=%s",
        project_id,
        task_type,
        [w.name for w in candidates],
        chosen.name if chosen else None,
    )
    return WorkerSelection(
        worker=chosen,
        blocked_busy=blocked_busy,
        blocked_unhealthy=blocked_unhealthy,
        blocked_rejected=blocked_rejected,
        blocked_task_type=blocked_task_type,
    )
