from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cairn.dispatcher.health_server import DispatcherHealthServer, DispatcherHealthState
from cairn.dispatcher.prompts.validation import validate_prompt_resources
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.scheduler.ai_overlay import AIOverlayCache
from cairn.dispatcher.scheduler.ai_worker_selector import AiWorkerSelector
from cairn.dispatcher.scheduler.cleanup import ContainerCleanupCoordinator
from cairn.dispatcher.scheduler.dispatch_coordinator import DispatchCoordinator
from cairn.dispatcher.scheduler.execution_config_resolver import ExecutionConfigResolver
from cairn.dispatcher.scheduler.health import DispatcherHealthCoordinator
from cairn.dispatcher.scheduler.log_state import LogState
from cairn.dispatcher.scheduler.project_cache import ProjectCaches
from cairn.dispatcher.scheduler.project_context import ProjectContextResolver
from cairn.dispatcher.scheduler.project_dispatcher import ProjectDispatcher
from cairn.dispatcher.scheduler.reload import DispatcherReloader
from cairn.dispatcher.scheduler.replay import ReplayCoordinator
from cairn.dispatcher.scheduler.runtime_maintenance import RuntimeMaintenance
from cairn.dispatcher.scheduler.runtime_state import RuntimeTaskRegistry
from cairn.dispatcher.scheduler.services import SchedulerServices
from cairn.dispatcher.scheduler.task_submitter import TaskSubmitter
from cairn.dispatcher.scheduler.tick_coordinator import TickCoordinator
from cairn.dispatcher.tasks.bootstrap import run_bootstrap_task
from cairn.dispatcher.tasks.explore import run_explore_task
from cairn.dispatcher.tasks.reason import run_reason_task
from cairn.observability.metrics import (
    DISPATCHER_INFLIGHT,
    DISPATCHER_TICKS,
)
from cairn.shared.config import DispatchConfig
from cairn.shared.contracts import (
    ProjectDetail,
)

LOG = logging.getLogger(__name__)


class DispatcherLoop:
    def __init__(self, config_path: Path):
        # Assembly is split into ordered phase methods for readability and to
        # make the wiring testable; the order is load-bearing (each phase
        # depends on attributes set by earlier ones) and must be preserved.
        self._init_core(config_path)
        self._init_health_server()
        self._init_runtime_state()
        self._init_worker_selection()
        self._init_containers()
        self._init_scheduler()

    def _init_core(self, config_path: Path) -> None:
        self.config_path = config_path
        self.config = DispatchConfig.load(config_path)
        validate_prompt_resources(self.config.runtime.prompt_group)
        self.client = CairnClient(self.config.server_url, api_token=self.config.system.auth.dispatcher_api_token)
        self._last_tick_at: float | None = None

    def _init_health_server(self) -> None:
        self.health_server = DispatcherHealthServer(
            *self._health_addr(),
            state=DispatcherHealthState(
                last_tick_at=lambda: self._last_tick_at,
            ),
            reload_handler=self._reload_from_health_server,
        )
        self.health_server.start()

    def _init_runtime_state(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=self.config.runtime.max_workers)
        self.runtime = RuntimeTaskRegistry()
        self.log_state = LogState()
        self.project_cursor = 0
        self._settings_checked = False
        self._startup_healthchecks_checked = False
        # Per-project caches: proxy, AI selection chains, and the
        # fetched ``sk`` values for the profiles in those chains.
        # See :mod:`cairn.dispatcher.scheduler.project_cache` for the
        # invalidation contract.
        self.project_caches = ProjectCaches()
        self._ai_overlay_cache = AIOverlayCache()
        self.execution_configs = ExecutionConfigResolver(self.client, self.log_state)
        self.replay = ReplayCoordinator(self.client, self.log_state)

    def _init_worker_selection(self) -> None:
        self.ai_worker_selector = AiWorkerSelector(
            config=self.config,
            worker_counts=self._worker_counts,
            worker_unhealthy_until=self.runtime.worker_unhealthy_until,
            worker_rejected_until=self.runtime.worker_rejected_until,
            secret_lookup=self.project_caches.get_ai_secret,
            overlay_lookup=self._ai_worker_env_overlay,
        )
        self.project_context = ProjectContextResolver(
            config=self.config,
            client=self.client,
            runtime=self.runtime,
            project_caches=self.project_caches,
            ai_overlay_cache=self._ai_overlay_cache,
            ai_worker_selector=self.ai_worker_selector,
        )

    def _init_containers(self) -> None:
        self.container_manager = ContainerManager(
            self.config.container,
            proxy_resolver=self.project_context.resolve_proxy_env,
        )
        self.health = DispatcherHealthCoordinator(
            config=self.config,
            client=self.client,
            container_manager=self.container_manager,
        )
        self.cleanup = ContainerCleanupCoordinator(
            self.container_manager,
            max_workers=self.config.runtime.max_workers,
        )

    def _init_scheduler(self) -> None:
        self.submitter = TaskSubmitter(
            config=self.config,
            client=self.client,
            container_manager=self.container_manager,
            executor=self.executor,
            runtime=self.runtime,
            log_state=self.log_state,
            execution_config_for=self._task_execution_config,
            select_worker=self.project_context.select_worker,
            project_open_intent_count=self._project_open_intent_count,
            release_intent=self._best_effort_release,
            release_reason=self._best_effort_release_reason,
            bootstrap_runner=run_bootstrap_task,
            explore_runner=run_explore_task,
            reason_runner=run_reason_task,
        )
        self.runtime_maintenance = RuntimeMaintenance(
            runtime=self.runtime,
            cleanup=self.cleanup,
            clear_project_log_state=self._clear_project_log_state,
        )
        self.scheduler_services = SchedulerServices(
            config=self.config,
            client=self.client,
            runtime=self.runtime,
            cleanup=self.cleanup,
            container_manager=self.container_manager,
            replay=self.replay,
            submitter=self.submitter,
            runtime_maintenance=self.runtime_maintenance,
            log_state=self.log_state,
            project_cursor_get=lambda: self.project_cursor,
            project_cursor_set=self._set_project_cursor,
            validate_server_settings=self._validate_server_settings,
            process_ai_profile_check_requests=self._process_ai_profile_check_requests,
            run_startup_healthchecks=self.run_startup_healthchecks,
            publish_tick_metrics=self._publish_tick_metrics,
            settings_checked_get=lambda: self._settings_checked,
            settings_checked_set=self._set_settings_checked,
            startup_healthchecks_checked_get=lambda: self._startup_healthchecks_checked,
        )
        self.project_dispatcher = ProjectDispatcher(self.scheduler_services)
        self.dispatch_coordinator = DispatchCoordinator(self.scheduler_services, self.project_dispatcher)
        self.tick_coordinator = TickCoordinator(self.scheduler_services, self.dispatch_coordinator)
        self.reloader = DispatcherReloader(self, self.config_path)

    def close(self) -> None:
        if self.runtime.futures:
            LOG.info(
                "dispatcher shutting down waiting_for_tasks=%s running_projects=%s",
                self.runtime.running_count(),
                sorted({task.project_id for task in self.runtime.futures.values()}),
            )
        self.executor.shutdown(wait=True)
        self.cleanup.shutdown(wait=True)
        self.container_manager.close()
        self.client.close()
        self.health_server.stop()

    def run(self, once: bool = False) -> None:
        """Main dispatcher loop."""
        try:
            while True:
                self._run_iteration(once=once)
                if once:
                    return
        finally:
            self.close()

    def _run_iteration(self, *, once: bool) -> None:
        """One scheduler tick."""
        self.tick_coordinator.run_iteration(once=once)

    def run_startup_healthchecks_only(self) -> None:
        try:
            self.run_startup_healthchecks(show_commands=True)
        finally:
            self.close()

    def run_startup_healthchecks(self, *, show_commands: bool = False) -> None:
        if self._startup_healthchecks_checked:
            return
        self._run_startup_healthchecks(show_commands=show_commands)
        self._startup_healthchecks_checked = True

    def _health_addr(self) -> tuple[str, int]:
        value = self.config.dispatcher.health_addr
        host, _, port_text = value.partition(":")
        return host or "127.0.0.1", int(port_text or "9100")

    def _publish_tick_metrics(self) -> None:
        self._last_tick_at = time.time()
        DISPATCHER_TICKS.inc()
        DISPATCHER_INFLIGHT.set(self.runtime.running_count())

    def _set_project_cursor(self, value: int) -> None:
        self.project_cursor = value

    def _set_settings_checked(self, value: bool) -> None:
        self._settings_checked = value

    def _reload_from_health_server(self, authorization: str | None) -> dict[str, object]:
        return self.reloader.reload_from_health_server(authorization)

    def _advance_replay_project(self, project_id: str) -> bool | None:
        return self.replay.advance_project(project_id)

    def _task_execution_config(self, project_id: str, task_type: str) -> dict | None:
        return self.execution_configs.get_task_execution_config(project_id, task_type)

    def _worker_counts(self) -> dict[str, int]:
        return self.runtime.worker_counts()

    def _ai_worker_env_overlay(self, project_id: str, snapshot) -> dict[str, str]:
        return self.project_context.ai_worker_env_overlay(project_id, snapshot)

    def _project_open_intent_count(self, project: ProjectDetail) -> int:
        return self.project_dispatcher.project_open_intent_count(project)

    def _best_effort_release(self, project_id: str, intent_id: str, worker_name: str) -> None:
        response = self.client.release(project_id, intent_id, worker_name)
        if not response.ok and response.status_code not in (403, 409):
            LOG.warning("release failed project=%s intent=%s worker=%s status=%s", project_id, intent_id, worker_name, response.status_code)

    def _best_effort_release_reason(self, project_id: str, worker_name: str, run_id: str | None = None) -> None:
        response = self.client.release_reason(project_id, worker_name, run_id)
        if not response.ok and response.status_code not in (403, 409):
            LOG.warning("reason release failed project=%s worker=%s status=%s", project_id, worker_name, response.status_code)

    def _log_changed(self, scope: str, level: int, message: str, *args: object) -> None:
        self.log_state.log_changed(LOG, scope, level, message, *args)

    def _clear_log_state(self, scope: str) -> None:
        self.log_state.clear(scope)

    def _clear_project_log_state(self, project_id: str) -> None:
        self.log_state.clear_project(project_id)

    def _process_ai_profile_check_requests(self) -> None:
        if not hasattr(self, "health"):
            return
        self.health.process_ai_profile_check_requests()

    def _validate_server_settings(self) -> None:
        self.health.validate_server_settings()

    def _run_startup_healthchecks(self, *, show_commands: bool) -> None:
        self.health.run_startup_healthchecks(show_commands=show_commands)
