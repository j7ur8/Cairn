from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from cairn.dispatcher.models import RunningTask
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cancellation import TaskCancellation
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.scheduler.log_state import LogState
from cairn.dispatcher.scheduler.runtime_state import RuntimeTaskRegistry
from cairn.dispatcher.scheduler.submission_registry import TaskSubmissionRegistry
from cairn.dispatcher.scheduler.task_claims import TaskClaimer
from cairn.dispatcher.scheduler.worker_selection import WorkerSelection
from cairn.shared.config import DispatchConfig, WorkerConfig
from cairn.shared.contracts import Intent, ProjectDetail

LOG = logging.getLogger(__name__)

BootstrapRunner = Callable[
    [DispatchConfig, CairnClient, ContainerManager, ProjectDetail, Intent, WorkerConfig, dict, TaskCancellation],
    str,
]
ExploreRunner = Callable[
    [DispatchConfig, CairnClient, ContainerManager, ProjectDetail, str, Intent, WorkerConfig, dict, TaskCancellation],
    str,
]
ReasonRunner = Callable[
    [
        DispatchConfig,
        CairnClient,
        ContainerManager,
        ProjectDetail,
        str,
        WorkerConfig,
        dict,
        str,
        str,
        str,
        int,
        int,
        int,
        TaskCancellation,
    ],
    str,
]


@dataclass(slots=True)
class SubmissionContext:
    project: ProjectDetail
    task_type: str
    execution_config: dict
    worker: WorkerConfig
    export_yaml: str | None = None

    @property
    def project_id(self) -> str:
        return self.project.project.id


class TaskSubmitter:
    def __init__(
        self,
        *,
        config: DispatchConfig,
        client: CairnClient,
        container_manager: ContainerManager,
        executor: ThreadPoolExecutor,
        runtime: RuntimeTaskRegistry,
        log_state: LogState,
        execution_config_for: Callable[[str, str], dict | None],
        select_worker: Callable[[ProjectDetail, str, dict], WorkerSelection],
        project_open_intent_count: Callable[[ProjectDetail], int],
        release_intent: Callable[[str, str, str], None],
        release_reason: Callable[[str, str, str | None], None],
        bootstrap_runner: BootstrapRunner,
        explore_runner: ExploreRunner,
        reason_runner: ReasonRunner,
    ) -> None:
        self.config = config
        self.client = client
        self.container_manager = container_manager
        self.executor = executor
        self.runtime = runtime
        self.log_state = log_state
        self.execution_config_for = execution_config_for
        self.select_worker = select_worker
        self.project_open_intent_count = project_open_intent_count
        self.claimer = TaskClaimer(
            client=client,
            release_intent=release_intent,
            release_reason=release_reason,
        )
        self.submissions = TaskSubmissionRegistry(runtime=runtime, log_state=log_state)
        self.bootstrap_runner = bootstrap_runner
        self.explore_runner = explore_runner
        self.reason_runner = reason_runner

    def refresh(
        self,
        *,
        config: DispatchConfig,
        client: CairnClient,
        container_manager: ContainerManager,
        executor: ThreadPoolExecutor,
        runtime: RuntimeTaskRegistry,
    ) -> None:
        self.config = config
        self.client = client
        self.container_manager = container_manager
        self.executor = executor
        self.runtime = runtime
        self.claimer.refresh(client=client)
        self.submissions.refresh(runtime=runtime)

    def dispatch_reason(self, project: ProjectDetail, trigger: str, trigger_hash: str) -> bool:
        context = self._prepare_submission(project, "reason", needs_export=True)
        if context is None:
            return False
        # needs_export=True guarantees a non-None export from _prepare_submission.
        export_yaml = context.export_yaml
        assert export_yaml is not None

        fact_count = len(project.facts)
        hint_count = len(project.hints)
        open_intent_count = self.project_open_intent_count(project)
        run_id = uuid.uuid4().hex
        if not self.claimer.claim_reason(
            project_id=context.project_id,
            worker_name=context.worker.name,
            trigger=trigger,
            run_id=run_id,
            trigger_hash=trigger_hash,
            fact_count=fact_count,
            hint_count=hint_count,
            open_intent_count=open_intent_count,
        ):
            return False

        return self.submissions.submit_and_register(
            task_type="reason",
            project_id=context.project_id,
            worker_name=context.worker.name,
            intent_id=None,
            release=lambda: self.claimer.release_claim(
                project_id=context.project_id,
                intent_id=None,
                worker_name=context.worker.name,
                run_id=run_id,
            ),
            submit=lambda cancellation: self.executor.submit(
                self.reason_runner,
                self.config,
                self.client,
                self.container_manager,
                project,
                export_yaml,
                context.worker,
                context.execution_config,
                run_id,
                trigger,
                trigger_hash,
                fact_count,
                hint_count,
                open_intent_count,
                cancellation,
            ),
            running_task=lambda cancellation: RunningTask(
                context.project_id,
                "reason",
                context.worker.name,
                cancellation,
                intent_id=None,
                fact_count=fact_count,
                hint_count=hint_count,
                open_intent_count=open_intent_count,
                reason_trigger=trigger,
                reason_trigger_hash=trigger_hash,
            ),
            success_log=lambda: LOG.info(
                "dispatched reason project=%s worker=%s trigger=%s",
                context.project_id,
                context.worker.name,
                trigger,
            ),
        )

    def dispatch_bootstrap(self, project: ProjectDetail, intent: Intent) -> bool:
        context = self._prepare_submission(project, "bootstrap", intent=intent)
        if context is None:
            return False
        if not self.claimer.claim_intent(
            task_type=context.task_type,
            project_id=context.project_id,
            intent=intent,
            worker_name=context.worker.name,
        ):
            return False

        return self.submissions.submit_and_register(
            task_type="bootstrap",
            project_id=context.project_id,
            worker_name=context.worker.name,
            intent_id=intent.id,
            release=lambda: self.claimer.release_claim(
                project_id=context.project_id,
                intent_id=intent.id,
                worker_name=context.worker.name,
                run_id=None,
            ),
            submit=lambda cancellation: self.executor.submit(
                self.bootstrap_runner,
                self.config,
                self.client,
                self.container_manager,
                project,
                intent,
                context.worker,
                context.execution_config,
                cancellation,
            ),
            running_task=lambda cancellation: RunningTask(
                context.project_id,
                "bootstrap",
                context.worker.name,
                cancellation,
                intent_id=intent.id,
            ),
            success_log=lambda: LOG.info(
                "dispatched bootstrap project=%s intent=%s worker=%s",
                context.project_id,
                intent.id,
                context.worker.name,
            ),
        )

    def dispatch_explore(self, project: ProjectDetail, intent: Intent) -> bool:
        context = self._prepare_submission(project, "explore", intent=intent, needs_export=True)
        if context is None:
            return False
        # needs_export=True guarantees a non-None export from _prepare_submission.
        export_yaml = context.export_yaml
        assert export_yaml is not None
        if not self.claimer.claim_intent(
            task_type=context.task_type,
            project_id=context.project_id,
            intent=intent,
            worker_name=context.worker.name,
        ):
            return False

        return self.submissions.submit_and_register(
            task_type="explore",
            project_id=context.project_id,
            worker_name=context.worker.name,
            intent_id=intent.id,
            release=lambda: self.claimer.release_claim(
                project_id=context.project_id,
                intent_id=intent.id,
                worker_name=context.worker.name,
                run_id=None,
            ),
            submit=lambda cancellation: self.executor.submit(
                self.explore_runner,
                self.config,
                self.client,
                self.container_manager,
                project,
                export_yaml,
                intent,
                context.worker,
                context.execution_config,
                cancellation,
            ),
            running_task=lambda cancellation: RunningTask(
                context.project_id,
                "explore",
                context.worker.name,
                cancellation,
                intent_id=intent.id,
            ),
            success_log=lambda: LOG.info(
                "dispatched explore project=%s intent=%s worker=%s",
                context.project_id,
                intent.id,
                context.worker.name,
            ),
        )

    def _prepare_submission(
        self,
        project: ProjectDetail,
        task_type: str,
        *,
        intent: Intent | None = None,
        needs_export: bool = False,
    ) -> SubmissionContext | None:
        project_id = project.project.id
        execution_config = self.execution_config_for(project_id, task_type)
        if execution_config is None:
            return None
        selection = self.select_worker(project, task_type, execution_config)
        worker = selection.worker
        if worker is None:
            self._log_no_worker(project_id, task_type, selection, intent)
            return None
        self.log_state.clear(f"project:{project_id}:worker:{task_type}")
        export_yaml = None
        if needs_export:
            try:
                export_yaml = self.client.export_project(project_id)
            except Exception:
                if intent is None:
                    LOG.exception("%s export failed project=%s worker=%s", task_type, project_id, worker.name)
                else:
                    LOG.exception(
                        "%s export failed project=%s intent=%s worker=%s",
                        task_type,
                        project_id,
                        intent.id,
                        worker.name,
                    )
                return None
        return SubmissionContext(
            project=project,
            task_type=task_type,
            execution_config=execution_config,
            worker=worker,
            export_yaml=export_yaml,
        )

    def _log_no_worker(
        self,
        project_id: str,
        task_type: str,
        selection: WorkerSelection,
        intent: Intent | None,
    ) -> None:
        if intent is None:
            self.log_state.log_changed(
                LOG,
                f"project:{project_id}:worker:{task_type}",
                logging.INFO,
                "no worker available for %s project=%s blocked_busy=%s blocked_unhealthy=%s blocked_rejected=%s",
                task_type,
                project_id,
                selection.blocked_busy,
                selection.blocked_unhealthy,
                selection.blocked_rejected,
            )
            return
        self.log_state.log_changed(
            LOG,
            f"project:{project_id}:worker:{task_type}",
            logging.INFO,
            "no worker available for %s project=%s intent=%s blocked_busy=%s blocked_unhealthy=%s blocked_rejected=%s",
            task_type,
            project_id,
            intent.id,
            selection.blocked_busy,
            selection.blocked_unhealthy,
            selection.blocked_rejected,
        )
