from __future__ import annotations

import logging
import time
from collections.abc import Callable

from cairn.dispatcher.ai_health import probe_snapshot
from cairn.dispatcher.scheduler.worker_select import choose_worker
from cairn.dispatcher.scheduler.worker_selection import WorkerSelection
from cairn.shared.config import DispatchConfig, WorkerConfig
from cairn.shared.contracts import ProjectAiProfileSnapshot

LOG = logging.getLogger(__name__)


class AiWorkerSelector:
    def __init__(
        self,
        *,
        config: DispatchConfig,
        worker_counts: Callable[[], dict[str, int]],
        worker_unhealthy_until: dict[str, float],
        worker_rejected_until: dict[tuple[str, str, str], float],
        secret_lookup: Callable[[str], dict[str, str | None]],
        overlay_lookup: Callable[[str, ProjectAiProfileSnapshot], dict[str, str]],
    ) -> None:
        self.config = config
        self.worker_counts = worker_counts
        self.worker_unhealthy_until = worker_unhealthy_until
        self.worker_rejected_until = worker_rejected_until
        self.secret_lookup = secret_lookup
        self.overlay_lookup = overlay_lookup

    def refresh(
        self,
        *,
        config: DispatchConfig,
        worker_unhealthy_until: dict[str, float],
        worker_rejected_until: dict[tuple[str, str, str], float],
    ) -> None:
        self.config = config
        self.worker_unhealthy_until = worker_unhealthy_until
        self.worker_rejected_until = worker_rejected_until

    def select_for_chain(
        self,
        project_id: str,
        task_type: str,
        snapshots: list[ProjectAiProfileSnapshot],
    ) -> WorkerSelection:
        now = time.time()
        running_counts = self.worker_counts()
        last_unavailable_reasons: list[str] = []
        for snap in snapshots:
            secrets = self.secret_lookup(project_id)
            cached_secret = secrets.get(snap.profile_id) or None
            try:
                health = probe_snapshot(snap, config=self.config, cached_secret=cached_secret)
            except Exception as exc:  # noqa: BLE001
                LOG.warning(
                    "ai profile probe raised project=%s profile=%s error=%s",
                    project_id, snap.profile_id, exc,
                )
                continue
            if not health.ok:
                bad = [item for item in health.checks if not item.ok]
                reason = (
                    f"{snap.profile_id}({snap.snapshot_worker_type}) "
                    f"health checks failed: " + "; ".join(
                        f"{item.name}={item.message or 'fail'}" for item in bad
                    )
                )
                last_unavailable_reasons.append(reason)
                LOG.info("ai profile unavailable project=%s profile=%s reason=%s", project_id, snap.profile_id, reason)
                continue
            overlay = self.overlay_lookup(project_id, snap)
            if not overlay and snap.snapshot_api_key_env:
                reason = (
                    f"{snap.profile_id}({snap.snapshot_worker_type}) env "
                    f"{snap.snapshot_api_key_env} not configured in execution config"
                )
                last_unavailable_reasons.append(reason)
                LOG.info("ai profile unavailable project=%s profile=%s reason=%s", project_id, snap.profile_id, reason)
                continue
            if not overlay:
                LOG.info("ai profile has no api_key_env project=%s profile=%s", project_id, snap.profile_id)
            matching_workers = [
                worker for worker in self.config.workers
                if worker.type == snap.snapshot_worker_type
            ]
            if not matching_workers:
                reason = f"{snap.profile_id}({snap.snapshot_worker_type}) no matching worker in dispatch.yaml"
                last_unavailable_reasons.append(reason)
                LOG.info("ai profile unavailable project=%s profile=%s reason=%s", project_id, snap.profile_id, reason)
                continue
            blocked_busy: list[str] = []
            blocked_unhealthy: list[str] = []
            blocked_rejected: list[str] = []
            blocked_task_type: list[str] = []
            candidates: list[WorkerConfig] = []
            for worker in matching_workers:
                if task_type not in worker.task_types:
                    blocked_task_type.append(worker.name)
                    continue
                running = running_counts.get(worker.name, 0)
                if running >= worker.max_running:
                    blocked_busy.append(f"{worker.name}({running}/{worker.max_running})")
                    continue
                unhealthy_until = self.worker_unhealthy_until.get(worker.name, 0)
                if unhealthy_until > now:
                    blocked_unhealthy.append(f"{worker.name}({unhealthy_until - now:.1f}s)")
                    continue
                rejected_until = self.worker_rejected_until.get((project_id, task_type, worker.name), 0)
                if rejected_until > now:
                    blocked_rejected.append(f"{worker.name}({rejected_until - now:.1f}s)")
                    continue
                candidates.append(worker)
            if not candidates:
                reason = (
                    f"{snap.profile_id}({snap.snapshot_worker_type}) no healthy candidate "
                    f"task_type={task_type} busy={blocked_busy} unhealthy={blocked_unhealthy} "
                    f"rejected={blocked_rejected} task_type_blocked={blocked_task_type}"
                )
                last_unavailable_reasons.append(reason)
                LOG.info("ai profile fallthrough project=%s profile=%s reason=%s", project_id, snap.profile_id, reason)
                continue
            ordered = choose_worker(candidates, running_counts)
            base = ordered[0]
            chosen = base.model_copy(update={"env": {**base.env, **overlay}})
            LOG.info(
                "ai profile selected project=%s profile=%s worker=%s task_type=%s",
                project_id, snap.profile_id, chosen.name, task_type,
            )
            return WorkerSelection(
                worker=chosen,
                blocked_busy=blocked_busy,
                blocked_unhealthy=blocked_unhealthy,
                blocked_rejected=blocked_rejected,
                blocked_task_type=blocked_task_type,
            )
        LOG.warning("ai selection exhausted project=%s task_type=%s reasons=%s", project_id, task_type, last_unavailable_reasons)
        return WorkerSelection(
            worker=None,
            blocked_busy=[],
            blocked_unhealthy=[],
            blocked_rejected=[],
            blocked_task_type=[],
        )
