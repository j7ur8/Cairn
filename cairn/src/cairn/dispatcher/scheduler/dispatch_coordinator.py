from __future__ import annotations

import logging

from cairn.observability.metrics import DISPATCHER_OVERFLOW
from cairn.shared.contracts import ProjectWorkSummary

LOG = logging.getLogger(__name__)


class DispatchCoordinator:
    def __init__(self, services, project_dispatcher) -> None:
        self.services = services
        self.project_dispatcher = project_dispatcher

    def dispatch_available(self, summaries: list[ProjectWorkSummary]) -> None:
        services = self.services
        if services.runtime.running_count() >= services.config.runtime.max_workers:
            DISPATCHER_OVERFLOW.labels(reason="max_workers").inc()
            services.log_changed(
                LOG,
                "dispatch/global",
                logging.INFO,
                "skip dispatch because max_workers reached running_tasks=%s",
                services.runtime.running_count(),
            )
            return
        active = [summary for summary in summaries if summary.status == "active"]
        if not active:
            services.log_changed(LOG, "dispatch/global", logging.INFO, "skip dispatch because no active projects")
            return

        running_projects = self.ordered_projects(
            [summary for summary in active if summary.id in services.runtime.project_ids]
        )
        idle_projects = self.ordered_projects(
            [summary for summary in active if summary.id not in services.runtime.project_ids]
        )

        dispatched = True
        while dispatched and services.runtime.running_count() < services.config.runtime.max_workers:
            dispatched = False
            for summary in running_projects:
                if self.project_dispatcher.try_dispatch_project(summary):
                    dispatched = True
                    if services.runtime.running_count() >= services.config.runtime.max_workers:
                        return
            if dispatched:
                continue
            if self.project_dispatcher.running_project_count(active) >= services.config.runtime.max_running_projects:
                services.log_changed(
                    LOG,
                    "dispatch/idle-limit",
                    logging.INFO,
                    "skip idle project dispatch because max_running_projects reached running_projects=%s",
                    self.project_dispatcher.running_project_count(active),
                )
                return
            for summary in idle_projects:
                if self.project_dispatcher.running_project_count(active) >= services.config.runtime.max_running_projects:
                    services.log_changed(
                        LOG,
                        "dispatch/idle-limit",
                        logging.INFO,
                        "stop idle project dispatch because max_running_projects reached running_projects=%s",
                        self.project_dispatcher.running_project_count(active),
                    )
                    return
                if self.project_dispatcher.try_dispatch_project(summary):
                    dispatched = True
                    break

    def ordered_projects(self, summaries: list[ProjectWorkSummary]) -> list[ProjectWorkSummary]:
        if not summaries:
            return []
        ids = [summary.id for summary in summaries]
        ids.sort()
        cursor = self.services.project_cursor_get()
        offset = cursor % len(ids)
        ordered_ids = ids[offset:] + ids[:offset]
        by_id = {summary.id: summary for summary in summaries}
        self.services.project_cursor_set(cursor + 1)
        return [by_id[project_id] for project_id in ordered_ids]
