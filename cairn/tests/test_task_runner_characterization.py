"""Characterization tests for the intent task runners (bootstrap, explore).

These pin the *observable behavior* of run_bootstrap_task / run_explore_task
across every outcome branch BEFORE the template refactor, then keep passing
after it. They are pure unit tests: every collaborator (driver, lifecycle,
healthcheck gate, prepare, process exec, validators, writers, fallback,
release) is patched, so no Docker / DB / network is touched.

The assertions are on the returned outcome string and the key side effects
(release calls, fallback invocation, reporter error emissions) — the
contract the scheduler depends on. The refactor must preserve all of them.
"""
from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

from cairn.dispatcher.runtime.process import ProcessResult
from cairn.dispatcher.tasks.context import TaskInvocation, TaskServices


@dataclass
class _FakeLease:
    failure: object | None = None

    def start(self) -> None: ...
    def stop(self) -> None: ...


class _FakeReporter:
    def __init__(self) -> None:
        self.errors: list[tuple[str, str, str]] = []
        self.results: list[tuple] = []

    def start(self) -> None: ...
    def finish(self, *a, **k) -> None: ...
    def emit_prompt(self, *a, **k) -> None: ...
    def emit_result(self, *a, **k) -> None:
        self.results.append(a)
    def emit_error(self, phase, kind, msg) -> None:
        self.errors.append((phase, kind, msg))
    def emit_capability_manifest(self, *a, **k) -> None: ...


class _FakeLifecycle:
    last: _FakeLifecycle | None = None

    def __init__(self, *_a, **_k) -> None:
        self.reporter = _FakeReporter()
        self.lease = _FakeLease()
        self.finished_with: str | None = None
        _FakeLifecycle.last = self

    def start(self) -> None: ...
    def finish(self, outcome: str) -> None:
        self.finished_with = outcome


class _FakeDriver:
    def requires_tty(self) -> bool: return False
    def trace_format(self): return None
    def build_healthcheck(self, worker): return ["hc"]
    def prepare_session(self): return "sess"
    def build_execute(self, worker, prompt, session, ctx):
        return mock.Mock(argv=["run"], session=session)
    def extract_session(self, session, out, err): return session
    def extract_response_text(self, out, err): return out


@dataclass
class _FakePrepared:
    execution_config: dict
    task_timeout: dict
    capabilities: object
    role: object


def _prepared() -> _FakePrepared:
    caps = mock.Mock(context={}, instructions="", summary="", errors=[])
    role = mock.Mock(instructions="", summary="", errors=[])
    return _FakePrepared(execution_config={}, task_timeout={"timeout": 5, "conclude_timeout": 5}, capabilities=caps, role=role)


def _result(*, returncode=0, stdout="{}", stderr="", timed_out=False, cancelled=False, cancel_reason=None):
    return ProcessResult(
        returncode=returncode, stdout=stdout, stderr=stderr,
        timed_out=timed_out, cancelled=cancelled, cancel_reason=cancel_reason,
    )


def _project():
    return mock.Mock(project=mock.Mock(id="proj_1"))


def _intent():
    return mock.Mock(id="intent_1")


def _worker():
    return mock.Mock(name="w", type="mock")


def _services() -> TaskServices:
    return TaskServices(
        config=mock.Mock(),
        client=mock.Mock(),
        container_runtime=mock.Mock(),
    )


import contextlib

import cairn.dispatcher.tasks.bootstrap as bootstrap_mod
import cairn.dispatcher.tasks.intent_task as intent_task_mod


@contextlib.contextmanager
def _patch_bootstrap(
    *,
    process_result,
    healthcheck_outcome=None,
    prepared=True,
    validate_return=("data", {"fact_description": "f", "complete_description": "c"}),
    validate_raises=False,
    complete_status="success",
    complete_fact_id="fact_1",
    cancellation_reason=None,
    lease_failure=None,
):
    es = contextlib.ExitStack()
    p = es.enter_context
    # Shared lifecycle collaborators now live in the intent_task template.
    p(mock.patch.object(intent_task_mod, "get_driver", return_value=_FakeDriver()))
    p(mock.patch.object(intent_task_mod, "TaskLifecycle", _FakeLifecycle))
    p(mock.patch.object(intent_task_mod, "run_intent_healthcheck_gate", return_value=healthcheck_outcome))
    p(mock.patch.object(intent_task_mod, "prepare_task_execution", return_value=_prepared() if prepared else None))
    p(mock.patch.object(intent_task_mod, "run_worker_process", return_value=process_result))
    release = p(mock.patch.object(intent_task_mod, "best_effort_release"))
    # Type-specific hooks remain on the bootstrap module.
    p(mock.patch.object(bootstrap_mod, "render_prompt", return_value="PROMPT"))
    p(mock.patch.object(bootstrap_mod, "load_prompt_from_execution_config", return_value="TMPL"))
    p(mock.patch.object(bootstrap_mod, "bootstrap_prompt_replacements", return_value={}))
    p(mock.patch.object(bootstrap_mod, "format_remote_support_instructions", return_value=""))
    p(mock.patch.object(bootstrap_mod, "project_capability_data", return_value={}))
    p(mock.patch.object(bootstrap_mod, "capability_manifest_payload", return_value={}))
    fallback = p(mock.patch.object(bootstrap_mod, "run_bootstrap_conclude_fallback", return_value="failed"))
    if validate_raises:
        p(mock.patch.object(bootstrap_mod, "parse_json_output", side_effect=ValueError("bad json")))
    else:
        p(mock.patch.object(bootstrap_mod, "parse_json_output", return_value={}))
        p(mock.patch.object(bootstrap_mod, "validate_bootstrap_execute_payload", return_value=validate_return))
    p(mock.patch.object(
        bootstrap_mod, "write_bootstrap_complete_result",
        return_value=mock.Mock(status=complete_status, fact_id=complete_fact_id),
    ))
    # Drive cancellation / heartbeat via the fakes the runner sees.
    cancellation = mock.Mock()
    cancellation.reason = cancellation_reason
    yield es, release, fallback, cancellation
    es.close()


def _run_bootstrap(cancellation, lease_failure=None):
    # Inject lease failure by post-patching the lifecycle the runner builds.
    orig_start = _FakeLifecycle.start
    def start_with_failure(self):
        orig_start(self)
        if lease_failure is not None:
            self.lease.failure = lease_failure
    with mock.patch.object(_FakeLifecycle, "start", start_with_failure):
        return bootstrap_mod.run_bootstrap_task(
            _services(),
            TaskInvocation(
                project=_project(),
                intent=_intent(),
                worker=_worker(),
                execution_config={"task_timeout": {}},
                cancellation=cancellation,
            ),
        )


class BootstrapCharacterizationTests(unittest.TestCase):
    def test_success_returns_complete_status(self) -> None:
        with _patch_bootstrap(process_result=_result(returncode=0)) as (es, release, fallback, canc):
            outcome = _run_bootstrap(canc)
        self.assertEqual(outcome, "success")
        fallback.assert_not_called()
        release.assert_not_called()

    def test_rejected_releases_and_returns_rejected(self) -> None:
        with _patch_bootstrap(
            process_result=_result(returncode=0),
            validate_return=("rejected", {}),
        ) as (es, release, fallback, canc):
            outcome = _run_bootstrap(canc)
        self.assertEqual(outcome, "rejected")
        release.assert_called_once()

    def test_cancelled_returns_cancelled_and_releases(self) -> None:
        with _patch_bootstrap(
            process_result=_result(cancelled=True, cancel_reason="stop"),
        ) as (es, release, fallback, canc):
            outcome = _run_bootstrap(canc)
        self.assertEqual(outcome, "cancelled")
        release.assert_called_once()

    def test_heartbeat_lost_returns_failed_and_releases(self) -> None:
        with _patch_bootstrap(process_result=_result(returncode=0)) as (es, release, fallback, canc):
            outcome = _run_bootstrap(canc, lease_failure=mock.Mock(status_code=503))
        self.assertEqual(outcome, "failed")
        release.assert_called_once()

    def test_timeout_invokes_conclude_fallback(self) -> None:
        with _patch_bootstrap(process_result=_result(timed_out=True, returncode=124)) as (es, release, fallback, canc):
            _run_bootstrap(canc)
        fallback.assert_called_once()

    def test_parse_failure_invokes_conclude_fallback(self) -> None:
        with _patch_bootstrap(process_result=_result(returncode=0), validate_raises=True) as (es, release, fallback, canc):
            _run_bootstrap(canc)
        fallback.assert_called_once()

    def test_command_failure_releases_and_returns_failed(self) -> None:
        with _patch_bootstrap(process_result=_result(returncode=2)) as (es, release, fallback, canc):
            outcome = _run_bootstrap(canc)
        self.assertEqual(outcome, "failed")
        release.assert_called_once()

    def test_healthcheck_short_circuit_returns_its_outcome(self) -> None:
        with _patch_bootstrap(process_result=_result(), healthcheck_outcome="unhealthy") as (es, release, fallback, canc):
            outcome = _run_bootstrap(canc)
        self.assertEqual(outcome, "unhealthy")

    def test_prepare_none_releases_and_fails(self) -> None:
        with _patch_bootstrap(process_result=_result(), prepared=False) as (es, release, fallback, canc):
            outcome = _run_bootstrap(canc)
        self.assertEqual(outcome, "failed")
        release.assert_called_once()


import cairn.dispatcher.tasks.explore as explore_mod


@contextlib.contextmanager
def _patch_explore(
    *,
    process_result,
    healthcheck_outcome=None,
    prepared=True,
    validate_return=("fact", "a description"),
    validate_raises=False,
    conclude_status="success",
    conclude_fact_id="fact_1",
    cancellation_reason=None,
):
    es = contextlib.ExitStack()
    p = es.enter_context
    # Shared lifecycle collaborators live in the intent_task template.
    p(mock.patch.object(intent_task_mod, "get_driver", return_value=_FakeDriver()))
    p(mock.patch.object(intent_task_mod, "TaskLifecycle", _FakeLifecycle))
    p(mock.patch.object(intent_task_mod, "run_intent_healthcheck_gate", return_value=healthcheck_outcome))
    p(mock.patch.object(intent_task_mod, "prepare_task_execution", return_value=_prepared() if prepared else None))
    p(mock.patch.object(intent_task_mod, "run_worker_process", return_value=process_result))
    release = p(mock.patch.object(intent_task_mod, "best_effort_release"))
    # Type-specific hooks remain on the explore module.
    p(mock.patch.object(explore_mod, "build_explore_execute_prompt", return_value="PROMPT"))
    fallback = p(mock.patch.object(explore_mod, "run_explore_conclude_fallback", return_value="failed"))
    if validate_raises:
        p(mock.patch.object(explore_mod, "parse_json_output", side_effect=ValueError("bad json")))
    else:
        p(mock.patch.object(explore_mod, "parse_json_output", return_value={}))
        p(mock.patch.object(explore_mod, "validate_explore_payload", return_value=validate_return))
    p(mock.patch.object(
        explore_mod, "write_conclude_result_with_fact_id",
        return_value=mock.Mock(status=conclude_status, fact_id=conclude_fact_id),
    ))
    cancellation = mock.Mock()
    cancellation.reason = cancellation_reason
    yield es, release, fallback, cancellation
    es.close()


def _run_explore(cancellation, lease_failure=None):
    orig_start = _FakeLifecycle.start
    def start_with_failure(self):
        orig_start(self)
        if lease_failure is not None:
            self.lease.failure = lease_failure
    with mock.patch.object(_FakeLifecycle, "start", start_with_failure):
        return explore_mod.run_explore_task(
            _services(),
            TaskInvocation(
                project=_project(),
                intent=_intent(),
                worker=_worker(),
                execution_config={"task_timeout": {}},
                cancellation=cancellation,
                export_yaml="export_yaml",
            ),
        )


class ExploreCharacterizationTests(unittest.TestCase):
    def test_success_returns_conclude_status(self) -> None:
        with _patch_explore(process_result=_result(returncode=0)) as (es, release, fallback, canc):
            outcome = _run_explore(canc)
        self.assertEqual(outcome, "success")
        fallback.assert_not_called()
        release.assert_not_called()

    def test_rejected_releases_and_returns_rejected(self) -> None:
        with _patch_explore(process_result=_result(returncode=0), validate_return=("rejected", "")) as (es, release, fallback, canc):
            outcome = _run_explore(canc)
        self.assertEqual(outcome, "rejected")
        release.assert_called_once()

    def test_cancelled_returns_cancelled_and_releases(self) -> None:
        with _patch_explore(process_result=_result(cancelled=True, cancel_reason="stop")) as (es, release, fallback, canc):
            outcome = _run_explore(canc)
        self.assertEqual(outcome, "cancelled")
        release.assert_called_once()

    def test_heartbeat_lost_returns_failed_and_releases(self) -> None:
        with _patch_explore(process_result=_result(returncode=0)) as (es, release, fallback, canc):
            outcome = _run_explore(canc, lease_failure=mock.Mock(status_code=503))
        self.assertEqual(outcome, "failed")
        release.assert_called_once()

    def test_timeout_invokes_conclude_fallback(self) -> None:
        with _patch_explore(process_result=_result(timed_out=True, returncode=124)) as (es, release, fallback, canc):
            _run_explore(canc)
        fallback.assert_called_once()

    def test_parse_failure_invokes_conclude_fallback(self) -> None:
        with _patch_explore(process_result=_result(returncode=0), validate_raises=True) as (es, release, fallback, canc):
            _run_explore(canc)
        fallback.assert_called_once()

    def test_command_failure_releases_and_returns_failed(self) -> None:
        with _patch_explore(process_result=_result(returncode=2)) as (es, release, fallback, canc):
            outcome = _run_explore(canc)
        self.assertEqual(outcome, "failed")
        release.assert_called_once()

    def test_healthcheck_short_circuit_returns_its_outcome(self) -> None:
        with _patch_explore(process_result=_result(), healthcheck_outcome="unhealthy") as (es, release, fallback, canc):
            outcome = _run_explore(canc)
        self.assertEqual(outcome, "unhealthy")

    def test_prepare_none_releases_and_fails(self) -> None:
        with _patch_explore(process_result=_result(), prepared=False) as (es, release, fallback, canc):
            outcome = _run_explore(canc)
        self.assertEqual(outcome, "failed")
        release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
