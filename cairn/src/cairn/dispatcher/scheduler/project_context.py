from __future__ import annotations

import logging

from cairn.dispatcher.scheduler.ai_overlay import AIOverlayCache, compute_ai_overlay
from cairn.dispatcher.scheduler.ai_worker_selector import AiWorkerSelector
from cairn.dispatcher.scheduler.project_cache import ProjectCaches
from cairn.dispatcher.scheduler.worker_selection import WorkerSelection, select_worker_default
from cairn.shared.config import DispatchConfig, WorkerConfig
from cairn.shared.contracts import ProjectAiProfileSnapshot, ProjectDetail

LOG = logging.getLogger(__name__)


class ProjectContextResolver:
    def __init__(
        self,
        *,
        config: DispatchConfig,
        client,
        runtime,
        project_caches: ProjectCaches,
        ai_overlay_cache: AIOverlayCache,
        ai_worker_selector: AiWorkerSelector,
    ) -> None:
        self.config = config
        self.client = client
        self.runtime = runtime
        self.project_caches = project_caches
        self.ai_overlay_cache = ai_overlay_cache
        self.ai_worker_selector = ai_worker_selector

    def refresh(self, *, config: DispatchConfig, client, runtime, ai_worker_selector: AiWorkerSelector) -> None:
        self.config = config
        self.client = client
        self.runtime = runtime
        self.ai_worker_selector = ai_worker_selector

    def resolve_project_ai_selection(self, project_id: str, task_type: str, execution_config: dict) -> None:
        try:
            snapshots = [
                ProjectAiProfileSnapshot.model_validate(item)
                for item in (execution_config.get("ai_profiles") or [])
                if isinstance(item, dict)
            ]
        except Exception as exc:  # noqa: BLE001
            LOG.warning(
                "project=%s task=%s execution config ai snapshot parse failed error=%s",
                project_id,
                task_type,
                exc,
            )
            self.project_caches.set_ai_chains(project_id, None)
            return
        ordered = sorted(
            [snap for snap in snapshots if snap.task_type == task_type],
            key=lambda snap: (0 if snap.role == "primary" else 1, snap.position),
        )
        if not ordered:
            self.project_caches.set_ai_chains(project_id, None)
            return
        self.project_caches.set_ai_chains(project_id, {task_type: ordered})
        secrets: dict[str, str | None] = {}
        for snap in ordered:
            if snap.profile_id not in secrets:
                secrets[snap.profile_id] = snap.snapshot_api_key_value
        self.project_caches.set_ai_secret(project_id, secrets)
        self.ai_overlay_cache.invalidate(project_id)
        LOG.info(
            "project=%s ai selection task_type=%s primary=%s fallback=%s",
            project_id,
            task_type,
            next((snap.profile_id for snap in ordered if snap.role == "primary"), None),
            [snap.profile_id for snap in ordered if snap.role == "fallback"],
        )

    def project_ai_snapshots(self, project_id: str, task_type: str) -> list[ProjectAiProfileSnapshot]:
        chains = self.project_caches.get_ai_chains(project_id) or {}
        return chains.get(task_type) or []

    def ai_worker_env_overlay(self, project_id: str, snapshot: ProjectAiProfileSnapshot) -> dict[str, str]:
        cached = self.ai_overlay_cache.get(project_id, snapshot)
        if cached is not None:
            return cached
        secrets = self.project_caches.get_ai_secret(project_id)
        cached_secret = secrets.get(snapshot.profile_id) or None
        overlay = compute_ai_overlay(
            snapshot,
            cached_secret=cached_secret,
        )
        self.ai_overlay_cache.put(project_id, snapshot, overlay)
        return overlay

    def select_worker(self, project: ProjectDetail, task_type: str, execution_config: dict) -> WorkerSelection:
        project_id = project.project.id
        self.resolve_project_ai_selection(project_id, task_type, execution_config)
        workers = self._workers_from_execution_config(project_id, execution_config)
        snapshots = self.project_ai_snapshots(project_id, task_type)
        if snapshots:
            return self.select_worker_for_ai_chain(project_id, task_type, snapshots, workers=workers)
        return self.select_worker_default(project_id, task_type, workers=workers)

    def select_worker_by_name(
        self,
        project: ProjectDetail,
        task_type: str,
        execution_config: dict,
        worker_name: str,
    ) -> WorkerSelection:
        project_id = project.project.id
        self.resolve_project_ai_selection(project_id, task_type, execution_config)
        workers = [worker for worker in self._workers_from_execution_config(project_id, execution_config) if worker.name == worker_name]
        snapshots = self.project_ai_snapshots(project_id, task_type)
        if snapshots:
            return self.select_worker_for_ai_chain(project_id, task_type, snapshots, workers=workers)
        return self.select_worker_default(project_id, task_type, workers=workers)

    def select_worker_default(
        self,
        project_id: str,
        task_type: str,
        *,
        workers: list[WorkerConfig] | None = None,
    ) -> WorkerSelection:
        return select_worker_default(
            project_id=project_id,
            task_type=task_type,
            workers=workers if workers is not None else self.config.workers,
            running_counts=self.runtime.worker_counts(),
            worker_unhealthy_until=self.runtime.worker_unhealthy_until,
            worker_rejected_until=self.runtime.worker_rejected_until,
        )

    def select_worker_for_ai_chain(
        self,
        project_id: str,
        task_type: str,
        snapshots: list[ProjectAiProfileSnapshot],
        *,
        workers: list[WorkerConfig] | None = None,
    ) -> WorkerSelection:
        return self.ai_worker_selector.select_for_chain(project_id, task_type, snapshots, workers=workers)

    def _workers_from_execution_config(self, project_id: str, execution_config: dict) -> list[WorkerConfig]:
        raw_workers = execution_config.get("workers")
        if not isinstance(raw_workers, list):
            return []
        try:
            workers = [
                WorkerConfig.model_validate(item)
                for item in raw_workers
                if isinstance(item, dict)
            ]
        except Exception as exc:  # noqa: BLE001
            LOG.warning("project=%s execution config workers parse failed error=%s", project_id, exc)
            return []
        return workers
