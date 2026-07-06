from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cloak_sidecar import CloakSidecarManager
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.scheduler.cleanup import ContainerCleanupCoordinator
from cairn.dispatcher.scheduler.log_state import LogState
from cairn.dispatcher.scheduler.replay import ReplayCoordinator
from cairn.dispatcher.scheduler.runtime_maintenance import RuntimeMaintenance
from cairn.dispatcher.scheduler.runtime_state import RuntimeTaskRegistry
from cairn.dispatcher.scheduler.task_submitter import TaskSubmitter
from cairn.shared.config import DispatchConfig
from cairn.shared.contracts import Intent, ProjectDetail, ProjectSummary


@dataclass(slots=True)
class SchedulerServices:
    config: DispatchConfig
    client: CairnClient
    runtime: RuntimeTaskRegistry
    cleanup: ContainerCleanupCoordinator
    container_manager: ContainerManager
    cloak_sidecar_manager: CloakSidecarManager | None
    replay: ReplayCoordinator
    submitter: TaskSubmitter
    runtime_maintenance: RuntimeMaintenance
    log_state: LogState
    project_cursor_get: Callable[[], int]
    project_cursor_set: Callable[[int], None]
    validate_server_settings: Callable[[], None]
    process_ai_profile_check_requests: Callable[[], None]
    run_startup_healthchecks: Callable[[], None]
    publish_tick_metrics: Callable[[], None]
    settings_checked_get: Callable[[], bool]
    settings_checked_set: Callable[[bool], None]
    startup_healthchecks_checked_get: Callable[[], bool]

    def log_changed(self, logger: logging.Logger, scope: str, level: int, message: str, *args: object) -> None:
        self.log_state.log_changed(logger, scope, level, message, *args)

    def refresh(
        self,
        *,
        config: DispatchConfig,
        client: CairnClient,
        container_manager: ContainerManager,
        cloak_sidecar_manager: CloakSidecarManager | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.container_manager = container_manager
        self.cloak_sidecar_manager = cloak_sidecar_manager

    def clear_project_log_state(self, project_id: str) -> None:
        self.log_state.clear_project(project_id)

    def project_running_task_count(self, project_id: str) -> int:
        return self.runtime.project_task_count(project_id)

    def project_running_task_summary(self, project_id: str) -> list[str]:
        return self.runtime.project_task_summary(project_id)

    def project_has_running_bootstrap(self, project_id: str) -> bool:
        return self.runtime.has_running_bootstrap(project_id)

    def project_running_explore_intents(self, project_id: str) -> set[str]:
        return self.runtime.running_explore_intents(project_id)

    def running_project_count(self, summaries: list[ProjectSummary]) -> int:
        return self.runtime.running_project_count(summaries)

    def reason_checkpoint(self, project_id: str):
        return self.runtime.reason_checkpoints.get(project_id)

    def dispatch_reason(self, project: ProjectDetail, trigger: str, trigger_hash: str) -> bool:
        return self.submitter.dispatch_reason(project, trigger, trigger_hash)

    def dispatch_bootstrap(self, project: ProjectDetail, intent: Intent) -> bool:
        return self.submitter.dispatch_bootstrap(project, intent)

    def dispatch_explore(self, project: ProjectDetail, intent: Intent) -> bool:
        return self.submitter.dispatch_explore(project, intent)

    def advance_replay_project(self, project_id: str) -> bool | None:
        return self.replay.advance_project(project_id)
