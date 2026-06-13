from __future__ import annotations

import time


class TickCoordinator:
    def __init__(self, services, dispatch_coordinator) -> None:
        self.services = services
        self.dispatch_coordinator = dispatch_coordinator

    def run_iteration(self, *, once: bool) -> None:
        services = self.services
        if not services.startup_healthchecks_checked_get():
            services.run_startup_healthchecks()
        if not services.settings_checked_get():
            services.validate_server_settings()
            services.settings_checked_set(True)
        services.process_ai_profile_check_requests()
        services.runtime_maintenance.reap_futures()
        services.runtime_maintenance.reap_cleanup_futures()
        summaries = services.client.list_project_work()
        services.runtime_maintenance.initialize_reason_checkpoints(summaries)
        services.runtime_maintenance.refresh_runtime_projects(summaries)
        services.runtime_maintenance.cancel_inactive_tasks(summaries)
        services.cleanup.queue_for_projects(summaries)
        self.dispatch_coordinator.dispatch_available(summaries)
        services.publish_tick_metrics()
        if once:
            return
        time.sleep(services.config.runtime.interval)
