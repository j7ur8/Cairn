from __future__ import annotations

import logging

from cairn.dispatcher.scheduler.frontier_priority import intent_priority_key
from cairn.dispatcher.scheduler.work_planner import (
    BOOTSTRAP_INTENT_CREATOR,
    BOOTSTRAP_INTENT_DESCRIPTION,
    bootstrap_intent,
    bootstrap_intent_count,
    is_bootstrap_intent,
    is_initial_project,
    project_open_intent_count,
    reason_trigger,
    summary_reason_might_run,
)
from cairn.shared.contracts import Intent, ProjectDetail, ProjectSummary, ProjectWorkSummary

LOG = logging.getLogger(__name__)


class ProjectDispatcher:
    def __init__(self, services) -> None:
        self.services = services

    def try_dispatch_project(self, summary: ProjectWorkSummary) -> bool:
        services = self.services
        skip_scope = f"project:{summary.id}:skip"
        container_name = services.container_manager.container_name(summary.id)
        if services.cleanup.is_pending(container_name):
            services.log_changed(
                LOG,
                f"{skip_scope}:cleanup_pending",
                logging.DEBUG,
                "skip project=%s because container cleanup is still pending container=%s",
                summary.id,
                container_name,
            )
            return False
        if services.project_running_task_count(summary.id) >= services.config.runtime.max_project_workers:
            services.log_changed(
                LOG,
                f"{skip_scope}:max_project_workers",
                logging.INFO,
                "skip project=%s because max_project_workers reached running_tasks=%s",
                summary.id,
                services.project_running_task_summary(summary.id),
            )
            return False

        if summary.status != "active":
            services.log_changed(
                LOG,
                f"{skip_scope}:status",
                logging.INFO,
                "skip project=%s because status=%s",
                summary.id,
                summary.status,
            )
            return False
        if summary.reason is not None and summary.unclaimed_intent_count == 0:
            services.log_changed(
                LOG,
                f"{skip_scope}:reason_claimed_light",
                logging.DEBUG,
                "skip project=%s because reason is claimed by %s and no unclaimed intents exist",
                summary.id,
                summary.reason.worker,
            )
            return False
        if (
            summary.fact_count > 2
            and summary.unclaimed_intent_count == 0
            and summary.reason is None
            and not self.summary_reason_might_run(summary)
        ):
            services.log_changed(
                LOG,
                f"{skip_scope}:no_light_work",
                logging.DEBUG,
                "skip project=%s because lightweight summary has no runnable work",
                summary.id,
            )
            return False

        replay_action = services.advance_replay_project(summary.id)
        if replay_action is not None:
            return replay_action
        project = services.client.get_project(summary.id)
        if project.project.status != "active":
            services.log_changed(
                LOG,
                f"{skip_scope}:status",
                logging.INFO,
                "skip project=%s because status=%s",
                summary.id,
                project.project.status,
            )
            return False
        if is_initial_project(project):
            if project.project.reason is not None:
                return False
            return self.dispatch_initial_project(project)
        running_intent_ids = services.project_running_explore_intents(summary.id)
        unclaimed_intents = [
            intent
            for intent in project.intents
            if intent.to is None
            and intent.worker is None
            and intent.id not in running_intent_ids
            and not is_bootstrap_intent(intent)
        ]
        if running_intent_ids and not unclaimed_intents:
            services.log_changed(
                LOG,
                f"{skip_scope}:explore_running",
                logging.DEBUG,
                "skip explore project=%s because all unclaimed intents are already running locally intents=%s",
                summary.id,
                sorted(running_intent_ids),
            )
        if unclaimed_intents:
            selected = max(unclaimed_intents, key=intent_priority_key)
            return services.dispatch_explore(project, selected)
        open_intent_count = self.project_open_intent_count(project)
        if open_intent_count > 0:
            open_intent_ids = [
                intent.id
                for intent in project.intents
                if intent.to is None and (intent.worker is not None or intent.id in running_intent_ids)
            ]
            services.log_changed(
                LOG,
                f"{skip_scope}:open_intents_pending",
                logging.DEBUG,
                "skip reason project=%s because open intents are still pending open_intents=%s "
                "unclaimed_intents=%s running_or_claimed_intents=%s",
                summary.id,
                open_intent_count,
                summary.unclaimed_intent_count,
                sorted(open_intent_ids),
            )
            return False
        if project.project.reason is not None:
            services.log_changed(
                LOG,
                f"{skip_scope}:reason_claimed",
                logging.DEBUG,
                "skip reason project=%s because reason is already claimed by %s",
                summary.id,
                project.project.reason.worker,
            )
            return False
        reason = self.reason_trigger(project)
        if reason is None:
            services.log_changed(
                LOG,
                f"{skip_scope}:graph_unchanged",
                logging.DEBUG,
                "skip reason project=%s because reason state unchanged facts=%s hints=%s open_intents=%s intents=%s",
                summary.id,
                len(project.facts),
                len(project.hints),
                open_intent_count,
                len(project.intents),
            )
            return False
        return services.dispatch_reason(project, reason.trigger, reason.trigger_hash)

    def dispatch_initial_project(self, project: ProjectDetail) -> bool:
        services = self.services
        intent = self.get_bootstrap_intent(project)
        if intent is None:
            intent = self.create_bootstrap_intent(project.project.id)
            if intent is None:
                return False
        if services.project_has_running_bootstrap(project.project.id):
            services.log_changed(
                LOG,
                f"project:{project.project.id}:skip:bootstrap_running",
                logging.DEBUG,
                "skip bootstrap project=%s because bootstrap task is already running locally",
                project.project.id,
            )
            return False
        if intent.worker is not None:
            services.log_changed(
                LOG,
                f"project:{project.project.id}:skip:bootstrap_claimed",
                logging.DEBUG,
                "skip bootstrap project=%s because bootstrap intent=%s is already claimed by %s",
                project.project.id,
                intent.id,
                intent.worker,
            )
            return False
        return services.dispatch_bootstrap(project, intent)

    def get_bootstrap_intent(self, project: ProjectDetail) -> Intent | None:
        if bootstrap_intent_count(project) > 1:
            LOG.warning(
                "project has multiple bootstrap intents project=%s intents=%s",
                project.project.id,
                [intent.id for intent in project.intents if is_bootstrap_intent(intent)],
            )
        return bootstrap_intent(project)

    def create_bootstrap_intent(self, project_id: str) -> Intent | None:
        response = self.services.client.create_intent(
            project_id,
            ["origin"],
            BOOTSTRAP_INTENT_DESCRIPTION,
            BOOTSTRAP_INTENT_CREATOR,
        )
        if response.status_code == 403:
            LOG.info("project became inactive before bootstrap intent create project=%s", project_id)
            return None
        if not response.ok:
            LOG.warning(
                "bootstrap intent write failed project=%s status=%s body=%s",
                project_id,
                response.status_code,
                response.text,
            )
            return None
        if not isinstance(response.data, dict):
            LOG.warning("bootstrap intent create returned empty body project=%s", project_id)
            return None
        intent = Intent.model_validate(response.data)
        LOG.info("created bootstrap intent project=%s intent=%s", project_id, intent.id)
        return intent

    def reason_trigger(self, project: ProjectDetail):
        return reason_trigger(project, self.services.reason_checkpoint(project.project.id))

    def summary_reason_might_run(self, summary: ProjectWorkSummary) -> bool:
        return summary_reason_might_run(summary, self.services.reason_checkpoint(summary.id))

    def project_open_intent_count(self, project: ProjectDetail) -> int:
        return project_open_intent_count(project)

    def running_project_count(self, summaries: list[ProjectSummary]) -> int:
        return self.services.running_project_count(summaries)
