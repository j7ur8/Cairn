from __future__ import annotations

import os
import sys
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


def _ts(value: int = 0) -> str:
    return f"2026-06-06T00:00:{value:02d}Z"


def _intent(
    intent_id: str,
    *,
    description: str = "investigate",
    creator: str = "worker",
    worker: str | None = None,
    to: str | None = None,
):
    from cairn.shared.contracts import Intent

    return Intent(
        id=intent_id,
        **{"from": ["origin"]},
        to=to,
        description=description,
        creator=creator,
        worker=worker,
        created_at=_ts(int(intent_id[-1]) if intent_id[-1].isdigit() else 0),
        concluded_at=None,
    )


def _project(*, intents=None, facts=None, hints=None):
    from cairn.shared.contracts import Fact, ProjectDetail, ProjectMeta

    return ProjectDetail(
        project=ProjectMeta(id="proj_001", title="T", status="active", created_at=_ts()),
        facts=facts
        or [
            Fact(id="origin", description="origin"),
            Fact(id="goal", description="goal"),
        ],
        intents=intents or [],
        hints=hints or [],
        proxy=None,
    )


class WorkPlannerTests(unittest.TestCase):
    def test_bootstrap_and_reason_helpers_are_pure(self) -> None:
        from cairn.dispatcher.models import ReasonCheckpoint
        from cairn.dispatcher.scheduler.work_planner import (
            bootstrap_intent,
            is_initial_project,
            project_open_intent_count,
            reason_trigger,
            summary_reason_might_run,
        )
        from cairn.shared.contracts import Fact, ProjectWorkSummary

        bootstrap = _intent(
            "i001",
            description="bootstrap",
            creator="dispatcher.bootstrap",
        )
        normal = _intent("i002")
        project = _project(intents=[normal, bootstrap])

        self.assertIs(bootstrap_intent(project), bootstrap)
        self.assertFalse(is_initial_project(project))
        self.assertEqual(project_open_intent_count(project), 2)

        changed = _project(
            intents=[],
            facts=[
                Fact(id="origin", description="origin"),
                Fact(id="goal", description="goal"),
                Fact(id="f001", description="new"),
            ],
        )
        trigger = reason_trigger(
            changed,
            ReasonCheckpoint(fact_count=2, hint_count=0, open_intent_count=1),
        )
        self.assertIsNotNone(trigger)
        assert trigger is not None
        self.assertEqual(trigger.trigger, "facts:2->3,open_intents:1->0")

        summary = ProjectWorkSummary(
            id="proj_001",
            title="T",
            status="active",
            created_at=_ts(),
            fact_count=3,
            intent_count=0,
            working_intent_count=0,
            unclaimed_intent_count=0,
            hint_count=0,
        )
        self.assertTrue(
            summary_reason_might_run(
                summary,
                ReasonCheckpoint(fact_count=2, hint_count=0, open_intent_count=0),
            )
        )


class RuntimeTaskRegistryTests(unittest.TestCase):
    def test_reap_done_returns_outcomes_and_exceptions(self) -> None:
        from cairn.dispatcher.models import RunningTask
        from cairn.dispatcher.runtime.cancellation import TaskCancellation
        from cairn.dispatcher.scheduler.runtime_state import RuntimeTaskRegistry

        registry = RuntimeTaskRegistry()
        ok: Future[str] = Future()
        bad: Future[str] = Future()
        registry.add(ok, RunningTask("proj_001", "explore", "mock", TaskCancellation(), intent_id="i001"))
        registry.add(bad, RunningTask("proj_002", "reason", "mock", TaskCancellation()))
        ok.set_result("success")
        error = RuntimeError("boom")
        bad.set_exception(error)

        results = registry.reap_done()

        by_project = {task.project_id: (outcome, exc) for task, outcome, exc in results}
        self.assertEqual(by_project["proj_001"], ("success", None))
        self.assertIs(by_project["proj_002"][1], error)
        self.assertEqual(registry.running_count(), 0)

    def test_record_reason_success_updates_checkpoint(self) -> None:
        from cairn.dispatcher.models import RunningTask
        from cairn.dispatcher.runtime.cancellation import TaskCancellation
        from cairn.dispatcher.scheduler.runtime_state import RuntimeTaskRegistry

        registry = RuntimeTaskRegistry()
        task = RunningTask(
            "proj_001",
            "reason",
            "mock",
            TaskCancellation(),
            fact_count=5,
            hint_count=2,
            open_intent_count=0,
        )
        registry.record_task_outcome(task, "success")

        checkpoint = registry.reason_checkpoints["proj_001"]
        self.assertEqual(checkpoint.fact_count, 5)
        self.assertEqual(checkpoint.hint_count, 2)
        self.assertEqual(checkpoint.open_intent_count, 0)


class ContainerCleanupCoordinatorTests(unittest.TestCase):
    def test_queues_each_cleanup_scope_once_and_records_inactive_done(self) -> None:
        from cairn.dispatcher.scheduler.cleanup import ContainerCleanupCoordinator
        from cairn.shared.contracts import ProjectSummary

        class FakeContainerManager:
            def container_name(self, project_id: str) -> str:
                return f"cairn-{project_id}"

            def needs_completed_cleanup(self, project_id: str) -> bool:
                return True

            def cleanup_completed(self, project_id: str) -> bool:
                return True

            def needs_stopped_cleanup(self, project_id: str) -> bool:
                return False

            def cleanup_stopped(self, project_id: str) -> bool:
                raise AssertionError("not called")

            def managed_container_names(self) -> list[str]:
                return ["cairn-orphan"]

            def needs_orphan_cleanup(self, container_name: str) -> bool:
                return True

            def cleanup_orphan(self, container_name: str) -> bool:
                return True

        coordinator = ContainerCleanupCoordinator(FakeContainerManager(), max_workers=2)  # type: ignore[arg-type]
        try:
            summaries = [
                ProjectSummary(
                    id="proj_done",
                    title="done",
                    status="completed",
                    created_at=_ts(),
                    fact_count=0,
                    intent_count=0,
                    working_intent_count=0,
                    unclaimed_intent_count=0,
                    hint_count=0,
                ),
                ProjectSummary(
                    id="proj_stop",
                    title="stop",
                    status="stopped",
                    created_at=_ts(),
                    fact_count=0,
                    intent_count=0,
                    working_intent_count=0,
                    unclaimed_intent_count=0,
                    hint_count=0,
                ),
            ]
            coordinator.queue_for_projects(summaries)
            coordinator.queue_for_projects(summaries)

            self.assertEqual(len(coordinator.pending), 2)
            for future in list(coordinator.futures):
                future.result(timeout=5)
            coordinator.reap()
            self.assertEqual(coordinator.inactive_done["proj_done"], "completed")
            self.assertEqual(coordinator.inactive_done["proj_stop"], "stopped")
            self.assertFalse(coordinator.pending)
        finally:
            coordinator.shutdown(wait=True, cancel_futures=True)


class TaskSubmitterTests(unittest.TestCase):
    def test_dispatcher_loop_isolates_transient_tick_errors_after_startup(self) -> None:
        import cairn.dispatcher.scheduler.loop as loop_mod

        loop = loop_mod.DispatcherLoop.__new__(loop_mod.DispatcherLoop)
        loop._startup_healthchecks_checked = True
        loop._settings_checked = True
        loop._transient_failure_count = 0
        loop._last_transient_error = None
        loop.tick_coordinator = MagicMock()
        loop.tick_coordinator.run_iteration.side_effect = RuntimeError("server temporarily unavailable")

        loop._run_iteration(once=True)

        self.assertEqual(loop._transient_failure_count, 1)
        self.assertIn("server temporarily unavailable", loop._last_transient_error)

    def test_dispatcher_reload_replaces_client_for_token_rotation(self) -> None:
        from pathlib import Path
        from unittest import mock

        import cairn.dispatcher.scheduler.reload as reload_mod

        old_client = MagicMock(name="old_client")
        old_container = MagicMock(name="old_container")
        old_executor = MagicMock(name="old_executor")
        old_cleanup_executor = MagicMock(name="old_cleanup_executor")
        next_client = MagicMock(name="next_client")
        next_config = MagicMock()
        next_config.server_url = "http://next"
        next_config.system.auth.dispatcher_api_token = "next-token"
        next_config.container = object()
        next_config.runtime.max_workers = 3
        next_config.workers = [object()]

        loop = MagicMock()
        loop.config.system.auth.dispatcher_api_token = "old-token"
        loop.client = old_client
        loop.container_manager = old_container
        loop.executor = old_executor
        loop.cleanup.refresh.return_value = old_cleanup_executor
        loop.project_context.resolve_proxy_env = MagicMock()
        loop.runtime.worker_unhealthy_until = {}
        loop.runtime.worker_rejected_until = {}

        with mock.patch.object(reload_mod, "load_dispatch_config", return_value=next_config), \
             mock.patch.object(reload_mod, "validate_prompt_resources"), \
             mock.patch.object(reload_mod, "ContainerManager", return_value=MagicMock(name="next_container")), \
             mock.patch.object(reload_mod, "ThreadPoolExecutor", return_value=MagicMock(name="next_executor")), \
             mock.patch.object(reload_mod, "CairnClient", return_value=next_client) as client_ctor:
            result = reload_mod.DispatcherReloader(loop, Path("config.yaml")).reload_from_health_server("Bearer old-token")

        self.assertEqual(result, {"ok": True, "workers": 1})
        client_ctor.assert_called_once_with("http://next", api_token="next-token")
        self.assertIs(loop.client, next_client)
        old_client.close.assert_called_once()

    def test_execution_config_resolver_caches_until_cleared(self) -> None:
        from cairn.dispatcher.protocol.client import ApiResult
        from cairn.dispatcher.scheduler.execution_config_resolver import ExecutionConfigResolver
        from cairn.dispatcher.scheduler.log_state import LogState

        client = MagicMock()
        client.get_project_execution_config.return_value = ApiResult(
            200,
            {
                "task_type": "bootstrap",
                "config_version": 1,
                "task_timeout": {"timeout": 5},
            },
        )
        resolver = ExecutionConfigResolver(client, LogState())

        first = resolver.get_task_execution_config("proj_001", "bootstrap")
        assert first is not None
        first["task_timeout"]["timeout"] = 99
        second = resolver.get_task_execution_config("proj_001", "bootstrap")

        self.assertIsNot(first, second)
        self.assertEqual(second, {"task_type": "bootstrap", "config_version": 1, "task_timeout": {"timeout": 5}})
        client.get_project_execution_config.assert_called_once_with("proj_001", "bootstrap")

        resolver.clear_project("proj_001")
        third = resolver.get_task_execution_config("proj_001", "bootstrap")
        self.assertEqual(third, {"task_type": "bootstrap", "config_version": 1, "task_timeout": {"timeout": 5}})
        self.assertEqual(client.get_project_execution_config.call_count, 2)

        resolver.clear_all()
        resolver.get_task_execution_config("proj_001", "bootstrap")
        self.assertEqual(client.get_project_execution_config.call_count, 3)

    def test_bootstrap_claim_and_task_use_same_frozen_execution_config(self) -> None:
        from cairn.dispatcher.protocol.client import ApiResult
        from cairn.dispatcher.runtime.cancellation import TaskCancellation
        from cairn.dispatcher.scheduler.log_state import LogState
        from cairn.dispatcher.scheduler.runtime_state import RuntimeTaskRegistry
        from cairn.dispatcher.scheduler.task_submitter import TaskSubmitter
        from cairn.dispatcher.scheduler.worker_selection import WorkerSelection
        from cairn.shared.config import WorkerConfig

        client = MagicMock()
        client.claim.return_value = ApiResult(200, {"ok": True})
        executor = ThreadPoolExecutor(max_workers=1)
        runtime = RuntimeTaskRegistry()
        worker = WorkerConfig(
            name="mock",
            type="mock",
            task_types=["bootstrap"],
            max_running=1,
            priority=0,
            env={},
        )
        selection = WorkerSelection(
            worker=worker,
            blocked_busy=[],
            blocked_unhealthy=[],
            blocked_rejected=[],
            blocked_task_type=[],
        )
        project = _project(intents=[])
        intent = _intent(
            "i001",
            description="bootstrap",
            creator="dispatcher.bootstrap",
        )

        def fake_run(services, invocation):
            self.assertIs(services.config, submitter.config)
            self.assertIs(services.client, client)
            self.assertIs(services.container_runtime, submitter.container_manager)
            self.assertIs(invocation.project, project)
            self.assertIs(invocation.intent, intent)
            self.assertIs(invocation.worker, worker)
            self.assertEqual(invocation.execution_config["config_version"], 7)
            self.assertIsInstance(invocation.cancellation, TaskCancellation)
            return "success"

        try:
            execution_config_for = MagicMock(return_value={"task_type": "bootstrap", "config_version": 7})
            select_worker = MagicMock(return_value=selection)
            release_intent = MagicMock()
            submitter = TaskSubmitter(
                config=object(),  # type: ignore[arg-type]
                client=client,
                container_manager=object(),  # type: ignore[arg-type]
                executor=executor,
                runtime=runtime,
                log_state=LogState(),
                execution_config_for=execution_config_for,
                select_worker=select_worker,
                project_open_intent_count=MagicMock(return_value=0),
                release_intent=release_intent,
                release_reason=MagicMock(),
                bootstrap_runner=fake_run,
                explore_runner=MagicMock(),
                reason_runner=MagicMock(),
            )

            dispatched = submitter.dispatch_bootstrap(project, intent)
            self.assertTrue(dispatched)
            for future in runtime.futures:
                future.result(timeout=5)
            client.claim.assert_called_once_with("proj_001", "i001", "mock")
            execution_config_for.assert_called_once_with("proj_001", "bootstrap")
            select_worker.assert_called_once_with(project, "bootstrap", {"task_type": "bootstrap", "config_version": 7})
            release_intent.assert_not_called()
        finally:
            executor.shutdown(wait=True)


class ReasonLeaseGuardTests(unittest.TestCase):
    def test_reason_run_id_guard_requires_exact_match(self) -> None:
        from cairn.server.domain.errors import DomainError
        from cairn.server.domain.reason import _check_reason_run_id_or_409

        _check_reason_run_id_or_409("run-1", "run-1")
        _check_reason_run_id_or_409(None, None)
        for current, supplied in (("run-1", None), ("run-1", "run-2"), (None, "run-1")):
            with self.subTest(current=current, supplied=supplied):
                with self.assertRaises(DomainError) as ctx:
                    _check_reason_run_id_or_409(current, supplied)
                self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
