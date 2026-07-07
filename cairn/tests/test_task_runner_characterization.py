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

from cairn.dispatcher.prompting import render_prompt
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
    def supports_conclude(self): return True
    def build_healthcheck(self, worker): return ["hc"]
    def prepare_session(self): return "sess"
    def build_execute(self, worker, prompt, session, ctx):
        return mock.Mock(argv=["run"], session=session)
    def build_conclude(self, worker, prompt, session, ctx):
        return ["conclude", session, prompt]
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
    from cairn.shared.contracts import Fact, ProjectDetail, ProjectMeta

    return ProjectDetail(
        project=ProjectMeta(id="proj_1", title="T", status="active", created_at="2026-06-06T00:00:00Z"),
        facts=[
            Fact(id="origin", description="origin"),
            Fact(id="goal", description="goal"),
        ],
        intents=[],
        hints=[],
    )


def _intent():
    from cairn.shared.contracts import Intent

    return Intent(
        id="intent_1",
        **{"from": ["origin"]},
        to=None,
        description="intent description",
        creator="reason",
        worker=None,
        created_at="2026-06-06T00:00:00Z",
        concluded_at=None,
    )


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
import cairn.dispatcher.tasks.reason as reason_mod
from cairn.dispatcher.tasks.explore_prompt import build_explore_conclude_prompt


@contextlib.contextmanager
def _patch_bootstrap(
    *,
    process_result,
    healthcheck_outcome=None,
    prepared=True,
    validate_return=("fact", "f"),
    validate_raises=False,
    conclude_status="success",
    conclude_fact_id="fact_1",
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
    p(mock.patch.object(bootstrap_mod, "project_capability_data", return_value={}))
    p(mock.patch.object(bootstrap_mod, "capability_manifest_payload", return_value={}))
    fallback = p(mock.patch.object(bootstrap_mod, "run_bootstrap_conclude_fallback", return_value="failed"))
    if validate_raises:
        validate = p(mock.patch.object(bootstrap_mod, "parse_sentinel_fact_output", side_effect=ValueError("bad sentinel")))
        p(mock.patch.object(bootstrap_mod._BOOTSTRAP_SPEC, "validate", side_effect=validate))
    else:
        validate = p(mock.patch.object(bootstrap_mod._BOOTSTRAP_SPEC, "validate", return_value=validate_return))
    p(mock.patch.object(
        bootstrap_mod, "write_conclude_result_with_fact_id",
        return_value=mock.Mock(status=conclude_status, fact_id=conclude_fact_id),
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
    def test_process_tail_buffer_bounds_large_output(self) -> None:
        from cairn.dispatcher.runtime.process import _TextTailBuffer

        buffer = _TextTailBuffer(8)
        buffer.append("012345")
        buffer.append("6789abcdef")

        self.assertEqual(buffer.text(), "89abcdef")
        self.assertTrue(buffer.truncated)

    def test_prepare_task_execution_uses_default_capability_injection(self) -> None:
        import cairn.dispatcher.tasks.runner as runner_mod

        config = mock.Mock()
        client = mock.Mock()
        reporter = mock.Mock()
        role_injection = mock.Mock(summary="", errors=[])
        capability_injection = mock.Mock(summary="", errors=[], context={})
        with mock.patch.object(runner_mod, "project_execution_config", return_value={"task_timeout": {"timeout": 5}}), \
             mock.patch.object(runner_mod, "project_task_timeout", return_value={"timeout": 5}), \
             mock.patch.object(runner_mod, "project_capability_data", return_value={}), \
             mock.patch.object(runner_mod, "inject_project_capabilities", return_value=capability_injection) as inject_caps, \
             mock.patch.object(runner_mod, "project_role_data", return_value={}), \
             mock.patch.object(runner_mod, "inject_project_role", return_value=role_injection):
            prepared = runner_mod.prepare_task_execution(
                config=config,
                client=client,
                container_manager=mock.Mock(),
                container_name="worker",
                project_id="proj",
                task_type="explore",
                capability_scope="task",
                reporter=reporter,
                phase="phase",
            )

        self.assertIsNotNone(prepared)
        inject_caps.assert_called_once()
        self.assertIs(inject_caps.call_args.args[1], client)
        self.assertEqual(inject_caps.call_args.args[3], "worker")

    def test_role_instructions_do_not_render_inside_phase_prompt(self) -> None:
        template = (_REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts" / "default" / "bootstrap.md").read_text(
            encoding="utf-8"
        )

        prompt = render_prompt(
            template,
            {
                "origin": "origin",
                "goal": "goal",
                "hints": "[]",
                "capability_instructions": "",
                "role_instructions": "## Project Type\nThis is a CTF project.",
            },
        )

        task_section = prompt.split("## Output Requirements", 1)[0]
        self.assertNotIn("## Project Type\nThis is a CTF project.", task_section)
        self.assertNotIn("selected a primary role", prompt)

    def test_task_instruction_files_keep_hints_out_of_agent_instructions(self) -> None:
        from cairn.dispatcher.tasks.instruction_files import inject_task_instructions
        from cairn.dispatcher.workers.base import WorkerExecutionContext

        class Writer:
            def __init__(self):
                self.files = {}

            def write_text_file(self, _container_name, path, content):
                self.files[path] = content

            def write_directory(self, *_args, **_kwargs):
                raise AssertionError("unexpected directory write")

            def ensure_running(self, *_args, **_kwargs):
                return "runner"

            def build_exec_process(self, *_args, **_kwargs):
                raise AssertionError("unexpected exec")

            def finish(self):
                pass

        writer = Writer()
        context = WorkerExecutionContext(mcp_servers=[{"id": "cairn-resources"}])
        paths = inject_task_instructions(
            container_manager=writer,
            container_name="runner",
            project=None,
            project_id="proj",
            task_type="bootstrap",
            task_instance_id="task",
            role_instructions="## Role\nStable role text.",
            capability_instructions="Capability text.",
            context=context,
        )

        self.assertIn("Stable role text.", writer.files[paths.claude_md_path])
        self.assertIn("Capability text.", writer.files[paths.capabilities_context_path])
        self.assertNotIn("Hints", writer.files[paths.claude_md_path])
        self.assertNotIn("Hints", writer.files[paths.agents_md_path])
        self.assertIn('"hooks_enabled": false', writer.files[paths.policy_path])
        self.assertEqual(context.instruction_root, paths.instruction_root)

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

    def test_sentinel_fact_parse_is_used_for_success(self) -> None:
        with _patch_bootstrap(process_result=_result(returncode=0)) as (es, release, fallback, canc):
            parse = es.enter_context(mock.patch.object(bootstrap_mod, "parse_sentinel_fact_output", return_value="sentinel fact"))
            es.enter_context(mock.patch.object(
                bootstrap_mod._BOOTSTRAP_SPEC,
                "validate",
                side_effect=bootstrap_mod._validate,
            ))
            write = es.enter_context(mock.patch.object(
                bootstrap_mod,
                "write_conclude_result_with_fact_id",
                return_value=mock.Mock(status="success", fact_id="fact_1"),
            ))
            outcome = _run_bootstrap(canc)
        self.assertEqual(outcome, "success")
        parse.assert_called_once_with("{}")
        write.assert_called_once()

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

    def test_cancelled_before_start_releases_without_lifecycle_or_container(self) -> None:
        from cairn.dispatcher.runtime.cancellation import TaskCancellation

        cancellation = TaskCancellation()
        cancellation.cancel("deleted")
        services = _services()

        with mock.patch.object(intent_task_mod, "get_driver") as get_driver, \
             mock.patch.object(intent_task_mod, "TaskLifecycle") as lifecycle_cls, \
             mock.patch.object(intent_task_mod, "best_effort_release") as release:
            outcome = bootstrap_mod.run_bootstrap_task(
                services,
                TaskInvocation(
                    project=_project(),
                    intent=_intent(),
                    worker=_worker(),
                    execution_config={"task_timeout": {}},
                    cancellation=cancellation,
                ),
            )

        self.assertEqual(outcome, "cancelled")
        release.assert_called_once()
        get_driver.assert_not_called()
        lifecycle_cls.assert_not_called()
        services.container_runtime.ensure_running.assert_not_called()


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
        p(mock.patch.object(explore_mod, "parse_sentinel_fact_output", side_effect=ValueError("bad sentinel")))
        p(mock.patch.object(explore_mod, "parse_json_output", side_effect=ValueError("bad json")))
    else:
        p(mock.patch.object(explore_mod, "parse_sentinel_fact_output", side_effect=ValueError("bad sentinel")))
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
    def test_explore_conclude_prompt_does_not_include_role_instructions(self) -> None:
        config = mock.Mock()
        container_manager = mock.Mock()
        intent = _intent()

        prompt = build_explore_conclude_prompt(
            config=config,
            container_manager=container_manager,
            container_name="container",
            export_yaml="graph: []",
            project=_project(),
            intent=intent,
            execution_config={
                "prompt_snapshot": {
                    "prompts": {
                        "explore_conclude.md": (
                            "# Task\nsummary only\n\n## Context\n"
                            "### Graph\n```\n{graph_yaml}\n```\n"
                            "### Current Intent\n```\n{intent_id}\n```\n"
                            "### Current Intent Description\n```\n{intent_description}\n```\n"
                        )
                    }
                }
            },
        )

        self.assertNotIn("## Project Type", prompt)
        self.assertNotIn("selected a primary role", prompt)

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

    def test_sentinel_fact_parse_is_used_for_success(self) -> None:
        with _patch_explore(process_result=_result(returncode=0, stdout="MODEL OUT")) as (es, release, fallback, canc):
            parse = es.enter_context(mock.patch.object(explore_mod, "parse_sentinel_fact_output", return_value="sentinel fact"))
            parse_json = es.enter_context(mock.patch.object(explore_mod, "parse_json_output"))
            es.enter_context(mock.patch.object(explore_mod._EXPLORE_SPEC, "validate", side_effect=explore_mod._validate))
            write = es.enter_context(mock.patch.object(
                explore_mod,
                "write_conclude_result_with_fact_id",
                return_value=mock.Mock(status="success", fact_id="fact_1"),
            ))
            outcome = _run_explore(canc)
        self.assertEqual(outcome, "success")
        parse.assert_called_once_with("MODEL OUT")
        parse_json.assert_not_called()
        write.assert_called_once()

    def test_json_parse_fallback_is_retained_for_explore_success(self) -> None:
        with _patch_explore(process_result=_result(returncode=0, stdout="MODEL OUT")) as (es, release, fallback, canc):
            sentinel = es.enter_context(mock.patch.object(
                explore_mod,
                "parse_sentinel_fact_output",
                side_effect=ValueError("bad sentinel"),
            ))
            parse_json = es.enter_context(mock.patch.object(explore_mod, "parse_json_output", return_value={}))
            validate = es.enter_context(mock.patch.object(
                explore_mod,
                "validate_explore_payload",
                return_value=("fact", "json fact"),
            ))
            es.enter_context(mock.patch.object(explore_mod._EXPLORE_SPEC, "validate", side_effect=explore_mod._validate))
            outcome = _run_explore(canc)
        self.assertEqual(outcome, "success")
        sentinel.assert_called_once_with("MODEL OUT")
        parse_json.assert_called_once_with("MODEL OUT")
        validate.assert_called_once_with({})

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

    def test_conclude_only_uses_checkpoint_session_without_execute(self) -> None:
        from cairn.dispatcher.runtime.cancellation import TaskCancellation

        cancellation = TaskCancellation()
        with mock.patch.object(explore_mod, "get_driver", return_value=_FakeDriver()), \
             mock.patch.object(explore_mod, "TaskLifecycle", _FakeLifecycle), \
             mock.patch.object(explore_mod, "run_intent_healthcheck_gate", return_value=None), \
             mock.patch.object(explore_mod, "project_task_timeout", return_value={"conclude_timeout": 5}), \
             mock.patch.object(explore_mod, "run_explore_conclude_fallback", return_value="success") as fallback, \
             mock.patch.object(explore_mod, "run_intent_task") as full_runner:
            outcome = explore_mod.run_explore_task(
                _services(),
                TaskInvocation(
                    project=_project(),
                    intent=_intent(),
                    worker=_worker(),
                    execution_config={"task_timeout": {"conclude_timeout": 5}},
                    cancellation=cancellation,
                    export_yaml="export_yaml",
                    checkpoint_session_id="session-1",
                ),
            )

        self.assertEqual(outcome, "success")
        full_runner.assert_not_called()
        self.assertEqual(fallback.call_args.kwargs["session"], "session-1")

    def test_conclude_fallback_upserts_checkpoint_and_clears_on_success(self) -> None:
        from cairn.dispatcher.protocol.client import ApiResult
        from cairn.dispatcher.runtime.cancellation import TaskCancellation
        from cairn.dispatcher.tasks.explore_result import run_explore_conclude_fallback

        client = mock.Mock()
        client.upsert_intent_phase_checkpoint.return_value = ApiResult(200, {"checkpoint": {}})
        client.clear_intent_phase_checkpoint.return_value = ApiResult(200, {"checkpoint": None})
        client.mark_intent_phase_checkpoint_failed.return_value = ApiResult(200, {"checkpoint": {}})
        container = mock.Mock()
        container.ensure_running.return_value = "container"
        reporter = _FakeReporter()
        driver = _FakeDriver()

        with mock.patch("cairn.dispatcher.tasks.explore_result.build_explore_conclude_prompt", return_value="PROMPT"), \
             mock.patch("cairn.dispatcher.tasks.conclude_fallback.project_allows_conclude_fallback", return_value=True), \
             mock.patch("cairn.dispatcher.tasks.explore_result.run_task_process", return_value=_result(returncode=0, stdout="MODEL")), \
             mock.patch("cairn.dispatcher.tasks.explore_result.parse_sentinel_fact_output", return_value="fact text"), \
             mock.patch(
                 "cairn.dispatcher.tasks.explore_result.write_conclude_result_with_fact_id",
                 return_value=mock.Mock(status="success", fact_id="fact_1"),
             ):
            outcome = run_explore_conclude_fallback(
                config=mock.Mock(),
                client=client,
                container_manager=container,
                worker=_worker(),
                driver=driver,
                project=_project(),
                project_id="proj_1",
                intent=_intent(),
                export_yaml="graph: []",
                session="session-1",
                lease=_FakeLease(),
                cancellation=TaskCancellation(),
                reporter=reporter,
                conclude_timeout=5,
                execution_config={"task_timeout": {"conclude_timeout": 5}},
            )

        self.assertEqual(outcome, "success")
        client.upsert_intent_phase_checkpoint.assert_called_once()
        self.assertEqual(client.upsert_intent_phase_checkpoint.call_args.args[:3], ("proj_1", "intent_1", "explore_conclude"))
        self.assertEqual(client.upsert_intent_phase_checkpoint.call_args.kwargs["session_id"], "session-1")
        client.clear_intent_phase_checkpoint.assert_called_once_with("proj_1", "intent_1", "explore_conclude")
        client.mark_intent_phase_checkpoint_failed.assert_not_called()

    def test_conclude_fallback_marks_failed_and_releases_on_parse_error(self) -> None:
        from cairn.dispatcher.protocol.client import ApiResult
        from cairn.dispatcher.runtime.cancellation import TaskCancellation
        from cairn.dispatcher.tasks.explore_result import run_explore_conclude_fallback

        client = mock.Mock()
        client.upsert_intent_phase_checkpoint.return_value = ApiResult(200, {"checkpoint": {}})
        client.mark_intent_phase_checkpoint_failed.return_value = ApiResult(200, {"checkpoint": {}})
        client.release.return_value = ApiResult(200, {"ok": True})
        container = mock.Mock()
        container.ensure_running.return_value = "container"
        reporter = _FakeReporter()
        worker = _worker()

        with mock.patch("cairn.dispatcher.tasks.explore_result.build_explore_conclude_prompt", return_value="PROMPT"), \
             mock.patch("cairn.dispatcher.tasks.conclude_fallback.project_allows_conclude_fallback", return_value=True), \
             mock.patch("cairn.dispatcher.tasks.explore_result.run_task_process", return_value=_result(returncode=0, stdout="BAD")), \
             mock.patch("cairn.dispatcher.tasks.explore_result.parse_sentinel_fact_output", side_effect=ValueError("bad sentinel")):
            outcome = run_explore_conclude_fallback(
                config=mock.Mock(),
                client=client,
                container_manager=container,
                worker=worker,
                driver=_FakeDriver(),
                project=_project(),
                project_id="proj_1",
                intent=_intent(),
                export_yaml="graph: []",
                session="session-1",
                lease=_FakeLease(),
                cancellation=TaskCancellation(),
                reporter=reporter,
                conclude_timeout=5,
                execution_config={"task_timeout": {"conclude_timeout": 5}},
            )

        self.assertEqual(outcome, "failed")
        client.mark_intent_phase_checkpoint_failed.assert_called_once()
        self.assertIn("parse_error", client.mark_intent_phase_checkpoint_failed.call_args.kwargs["last_error"])
        client.release.assert_called_once_with("proj_1", "intent_1", worker.name)


class ReasonCharacterizationTests(unittest.TestCase):
    def test_cancelled_before_start_releases_without_lifecycle_or_container(self) -> None:
        from cairn.dispatcher.runtime.cancellation import TaskCancellation

        cancellation = TaskCancellation()
        cancellation.cancel("deleted")
        services = _services()

        with mock.patch.object(reason_mod, "get_driver") as get_driver, \
             mock.patch.object(reason_mod, "TaskLifecycle") as lifecycle_cls, \
             mock.patch.object(reason_mod, "best_effort_release_reason") as release_reason:
            outcome = reason_mod.run_reason_task(
                services,
                TaskInvocation(
                    project=_project(),
                    worker=_worker(),
                    execution_config={"task_timeout": {}},
                    cancellation=cancellation,
                    export_yaml="export_yaml",
                    reason_run_id="reason_run_1",
                    reason_trigger="facts:1",
                    reason_trigger_hash="hash",
                ),
            )

        self.assertEqual(outcome, "cancelled")
        release_reason.assert_called_once()
        get_driver.assert_not_called()
        lifecycle_cls.assert_not_called()
        services.container_runtime.ensure_running.assert_not_called()
        services.client.finish_reason.assert_not_called()


if __name__ == "__main__":
    unittest.main()
