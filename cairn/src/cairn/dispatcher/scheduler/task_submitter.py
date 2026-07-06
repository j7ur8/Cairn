from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from cairn.dispatcher.models import RunningTask
from cairn.dispatcher.protocol.client import CairnClient
from cairn.dispatcher.runtime.cloak_sidecar import (
    CloakSidecarManager,
    project_uses_cloak_mcp,
    render_cloak_templates,
)
from cairn.dispatcher.runtime.containers import ContainerManager
from cairn.dispatcher.scheduler.log_state import LogState
from cairn.dispatcher.scheduler.runtime_state import RuntimeTaskRegistry
from cairn.dispatcher.scheduler.submission_registry import TaskSubmissionRegistry
from cairn.dispatcher.scheduler.task_claims import TaskClaimer
from cairn.dispatcher.scheduler.worker_selection import WorkerSelection
from cairn.dispatcher.tasks.context import TaskInvocation, TaskServices
from cairn.shared.config import ContainerConfig, DispatchConfig, WorkerConfig
from cairn.shared.contracts import Intent, ProjectDetail

LOG = logging.getLogger(__name__)

TaskRunner = Callable[[TaskServices, TaskInvocation], str]


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


@dataclass(slots=True)
class ProjectContainerRuntime:
    base: ContainerManager
    container_config: ContainerConfig | None

    def ensure_running(self, project_id: str, container_config: ContainerConfig | None = None) -> str:
        return self.base.ensure_running(project_id, container_config or self.container_config)

    def build_exec_process(self, *args, **kwargs):
        return self.base.build_exec_process(*args, **kwargs)

    def write_text_file(self, *args, **kwargs):
        return self.base.write_text_file(*args, **kwargs)

    def write_directory(self, *args, **kwargs):
        return self.base.write_directory(*args, **kwargs)


class TaskSubmitter:
    def __init__(
        self,
        *,
        config: DispatchConfig,
        client: CairnClient,
        container_manager: ContainerManager,
        cloak_sidecar_manager: CloakSidecarManager | None,
        executor: ThreadPoolExecutor,
        runtime: RuntimeTaskRegistry,
        log_state: LogState,
        execution_config_for: Callable[[str, str], dict | None],
        select_worker: Callable[[ProjectDetail, str, dict], WorkerSelection],
        select_worker_by_name: Callable[[ProjectDetail, str, dict, str], WorkerSelection],
        project_open_intent_count: Callable[[ProjectDetail], int],
        release_intent: Callable[[str, str, str], None],
        release_reason: Callable[[str, str, str | None], None],
        bootstrap_runner: TaskRunner,
        explore_runner: TaskRunner,
        reason_runner: TaskRunner,
    ) -> None:
        self.config = config
        self.client = client
        self.container_manager = container_manager
        self.cloak_sidecar_manager = cloak_sidecar_manager
        self.executor = executor
        self.runtime = runtime
        self.log_state = log_state
        self.execution_config_for = execution_config_for
        self.select_worker = select_worker
        self.select_worker_by_name = select_worker_by_name
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
        cloak_sidecar_manager: CloakSidecarManager | None = None,
        executor: ThreadPoolExecutor,
        runtime: RuntimeTaskRegistry,
    ) -> None:
        self.config = config
        self.client = client
        self.container_manager = container_manager
        self.cloak_sidecar_manager = cloak_sidecar_manager
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
                self._task_services(context.execution_config),
                TaskInvocation(
                    project=project,
                    worker=context.worker,
                    execution_config=context.execution_config,
                    cancellation=cancellation,
                    export_yaml=export_yaml,
                    reason_run_id=run_id,
                    reason_trigger=trigger,
                    reason_trigger_hash=trigger_hash,
                    fact_count=fact_count,
                    hint_count=hint_count,
                    open_intent_count=open_intent_count,
                ),
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
                self._task_services(context.execution_config),
                TaskInvocation(
                    project=project,
                    intent=intent,
                    worker=context.worker,
                    execution_config=context.execution_config,
                    cancellation=cancellation,
                ),
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
        if intent.phase_checkpoint is not None and intent.phase_checkpoint.phase == "explore_conclude":
            return self._dispatch_explore_conclude_only(project, intent)
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
                self._task_services(context.execution_config),
                TaskInvocation(
                    project=project,
                    intent=intent,
                    worker=context.worker,
                    execution_config=context.execution_config,
                    cancellation=cancellation,
                    export_yaml=export_yaml,
                ),
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

    def _dispatch_explore_conclude_only(self, project: ProjectDetail, intent: Intent) -> bool:
        checkpoint = intent.phase_checkpoint
        if checkpoint is None:
            return False
        context = self._prepare_submission(
            project,
            "explore",
            intent=intent,
            needs_export=True,
            worker_name=checkpoint.worker_name,
        )
        if context is None:
            return False
        if context.worker.name != checkpoint.worker_name or context.worker.type != checkpoint.worker_type:
            LOG.warning(
                "skip conclude-only because checkpoint worker no longer matches project=%s intent=%s checkpoint_worker=%s/%s selected=%s/%s",
                context.project_id,
                intent.id,
                checkpoint.worker_name,
                checkpoint.worker_type,
                context.worker.name,
                context.worker.type,
            )
            return False
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
                self._task_services(context.execution_config),
                TaskInvocation(
                    project=project,
                    intent=intent,
                    worker=context.worker,
                    execution_config=context.execution_config,
                    cancellation=cancellation,
                    export_yaml=export_yaml,
                    checkpoint_session_id=checkpoint.session_id,
                ),
            ),
            running_task=lambda cancellation: RunningTask(
                context.project_id,
                "explore",
                context.worker.name,
                cancellation,
                intent_id=intent.id,
            ),
            success_log=lambda: LOG.info(
                "dispatched explore conclude-only project=%s intent=%s worker=%s session=%s",
                context.project_id,
                intent.id,
                context.worker.name,
                checkpoint.session_id,
            ),
        )

    def _task_services(self, execution_config: dict) -> TaskServices:
        return TaskServices(
            config=self.config,
            client=self.client,
            container_runtime=ProjectContainerRuntime(
                self.container_manager,
                self._container_config_from_execution_config(execution_config),
            ),
        )

    def _container_config_from_execution_config(self, execution_config: dict) -> ContainerConfig | None:
        raw = execution_config.get("container")
        if not isinstance(raw, dict):
            return None
        try:
            return ContainerConfig.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("execution config container parse failed error=%s", exc)
            return None

    def _prepare_submission(
        self,
        project: ProjectDetail,
        task_type: str,
        *,
        intent: Intent | None = None,
        needs_export: bool = False,
        worker_name: str | None = None,
    ) -> SubmissionContext | None:
        project_id = project.project.id
        execution_config = self.execution_config_for(project_id, task_type)
        if execution_config is None:
            return None
        task_instance_id = intent.id if intent is not None else uuid.uuid4().hex
        execution_config = render_cloak_templates(execution_config, project_id, task_instance_id)
        selection = (
            self.select_worker_by_name(project, task_type, execution_config, worker_name)
            if worker_name is not None
            else self.select_worker(project, task_type, execution_config)
        )
        worker = selection.worker
        if worker is None:
            self._log_no_worker(project_id, task_type, selection, intent)
            return None
        self.log_state.clear(f"project:{project_id}:worker:{task_type}")
        if project_uses_cloak_mcp(execution_config):
            if self.cloak_sidecar_manager is None:
                LOG.warning("cloak sidecar selected but manager is unavailable project=%s task_type=%s", project_id, task_type)
                return None
            try:
                sidecar_status = self.cloak_sidecar_manager.ensure_running(
                    project_id,
                    network_mode=self.config.container.network_mode,
                )
                execution_config["cloak_sidecar"] = sidecar_status.model_dump()
            except Exception as exc:  # noqa: BLE001
                LOG.warning("cloak sidecar ensure failed project=%s task_type=%s error=%s", project_id, task_type, exc)
                return None
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
