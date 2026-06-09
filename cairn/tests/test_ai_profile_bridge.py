"""Bridge + health check tests for the AI profile system."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


def _make_config(*workers):
    """Build a minimal DispatchConfig-shaped stub for the probe."""
    from cairn.dispatcher.config import (
        DispatchConfig, RuntimeConfig, TasksConfig, ContainerConfig,
        BootstrapTaskConfig, ReasonTaskConfig, ExploreTaskConfig,
    )
    runtime = RuntimeConfig(
        interval=1, max_workers=1, max_project_workers=1,
        max_running_projects=1,
        healthcheck_timeout=1, prompt_group="g",
    )
    tasks = TasksConfig(
        bootstrap=BootstrapTaskConfig(timeout=5, conclude_timeout=5),
        reason=ReasonTaskConfig(timeout=5, max_intents=3),
        explore=ExploreTaskConfig(timeout=5, conclude_timeout=5),
    )
    container = ContainerConfig(
        image="cairn/test:latest", user=None, network_mode="cairn",
        completed_action="stop",
    )
    return DispatchConfig(
        server="http://localhost", runtime=runtime, tasks=tasks,
        container=container, workers=list(workers),
    )


def _claudecode(name="c1", model="m", base_url="https://api.example/anthropic", api_key="K", env_overrides=None, models=None, model_reasoning_effort=None):
    from cairn.dispatcher.config import WorkerConfig
    env = {"ANTHROPIC_MODEL": model, "ANTHROPIC_BASE_URL": base_url, "ANTHROPIC_AUTH_TOKEN": api_key}
    if env_overrides:
        env.update(env_overrides)
    return WorkerConfig(
        name=name, type="claudecode", task_types=["bootstrap"],
        max_running=1, priority=0, env=env, models=models or [],
        model_reasoning_effort=model_reasoning_effort,
    )


def _codex(name="x1", model="m", base_url="https://api.example/v1", api_key="K", models=None, model_reasoning_effort=None):
    from cairn.dispatcher.config import WorkerConfig
    return WorkerConfig(
        name=name, type="codex", task_types=["bootstrap"],
        max_running=1, priority=0,
        models=models or [],
        model_reasoning_effort=model_reasoning_effort,
        env={"CODEX_MODEL": model, "CODEX_BASE_URL": base_url, "OPENAI_API_KEY": api_key},
    )


class AuthEnvWarningTests(unittest.TestCase):
    def test_canonical_name_returns_none(self) -> None:
        from cairn.server.models import auth_env_warning
        self.assertIsNone(auth_env_warning("codex", "OPENAI_API_KEY"))
        self.assertIsNone(auth_env_warning("claudecode", "ANTHROPIC_AUTH_TOKEN"))

    def test_mismatch_returns_text(self) -> None:
        from cairn.server.models import auth_env_warning
        w = auth_env_warning("codex", "DEEPSEEK_KEY")
        self.assertIsNotNone(w)
        self.assertIn("OPENAI_API_KEY", w)


class HealthCheckSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        # Ensure a known env var is set for positive tests.
        os.environ["CAIRN_TEST_KEY_PRESENT"] = "yes"

    def tearDown(self) -> None:
        os.environ.pop("CAIRN_TEST_KEY_PRESENT", None)

    def _snap(self, **overrides):
        from cairn.server.models import ProjectAiProfileSnapshot
        defaults = dict(
            profile_id="p1", task_type="bootstrap", role="primary", position=0,
            snapshot_name="n", snapshot_worker_type="codex",
            snapshot_provider="", snapshot_base_url="",
            snapshot_model="m", snapshot_api_key_env="CAIRN_TEST_KEY_PRESENT",
        )
        defaults.update(overrides)
        return ProjectAiProfileSnapshot(**defaults)

    def test_auth_env_present_ok(self) -> None:
        from cairn.dispatcher.ai_health import probe_snapshot
        cfg = _make_config(_codex())
        result = probe_snapshot(self._snap(), config=cfg)
        # Auth + worker_type pass; base_url is empty so passes too.
        self.assertTrue(result.ok, [c.message for c in result.checks])
        names = {c.name for c in result.checks}
        self.assertIn("api_key_env_present", names)
        self.assertIn("base_url_reachable", names)
        self.assertIn("worker_type_declared", names)

    def test_auth_env_missing_fails(self) -> None:
        from cairn.dispatcher.ai_health import probe_snapshot
        cfg = _make_config(_codex())
        snap = self._snap(snapshot_api_key_env="CAIRN_TEST_KEY_MISSING")
        result = probe_snapshot(snap, config=cfg)
        self.assertFalse(result.ok)
        auth = next(c for c in result.checks if c.name == "api_key_env_present")
        self.assertFalse(auth.ok)
        self.assertIn("not set", auth.message)

    def test_canonical_guidance_for_openai_key(self) -> None:
        from cairn.dispatcher.ai_health import probe_snapshot
        cfg = _make_config(_codex())
        snap = self._snap(snapshot_api_key_env="OPENAI_API_KEY")
        result = probe_snapshot(snap, config=cfg)
        self.assertFalse(result.ok)


        auth = next(c for c in result.checks if c.name == "api_key_env_present")
        self.assertIn("define OPENAI_API_KEY directly", auth.message)

    def test_canonical_guidance_for_anthropic_key(self) -> None:
        from cairn.dispatcher.ai_health import probe_snapshot
        cfg = _make_config(_claudecode())
        snap = self._snap(
            snapshot_worker_type="claudecode",
            snapshot_api_key_env="ANTHROPIC_AUTH_TOKEN",
        )
        result = probe_snapshot(snap, config=cfg)
        self.assertFalse(result.ok)
        auth = next(c for c in result.checks if c.name == "api_key_env_present")
        self.assertIn("define ANTHROPIC_AUTH_TOKEN directly", auth.message)

    def test_auth_env_empty_fails(self) -> None:
        from cairn.dispatcher.ai_health import probe_snapshot
        os.environ["CAIRN_TEST_KEY_EMPTY"] = ""
        try:
            cfg = _make_config(_codex())
            snap = self._snap(snapshot_api_key_env="CAIRN_TEST_KEY_EMPTY")
            result = probe_snapshot(snap, config=cfg)
            self.assertFalse(result.ok)
            auth = next(c for c in result.checks if c.name == "api_key_env_present")
            self.assertFalse(auth.ok)
            self.assertIn("empty", auth.message)
        finally:
            os.environ.pop("CAIRN_TEST_KEY_EMPTY", None)

    def test_worker_type_undeclared_fails(self) -> None:
        from cairn.dispatcher.ai_health import probe_snapshot
        # No claudecode worker in the config; pick a snapshot with that type.
        cfg = _make_config(_codex())
        snap = self._snap(snapshot_worker_type="claudecode")
        result = probe_snapshot(snap, config=cfg)
        self.assertFalse(result.ok)
        wt = next(c for c in result.checks if c.name == "worker_type_declared")
        self.assertFalse(wt.ok)
        self.assertIn("claudecode", wt.message)

    def test_unreachable_base_url_fails(self) -> None:
        from cairn.dispatcher.ai_health import probe_snapshot
        cfg = _make_config(_codex())
        # 127.0.0.1:1 is reserved and will refuse connection.
        snap = self._snap(snapshot_base_url="http://127.0.0.1:1/")
        result = probe_snapshot(snap, config=cfg, timeout=0.5)
        self.assertFalse(result.ok)
        url = next(c for c in result.checks if c.name == "base_url_reachable")
        self.assertFalse(url.ok)

    def test_reachable_base_url_ok(self) -> None:
        from cairn.dispatcher.ai_health import probe_snapshot

        # Spin up a tiny HTTP server on an ephemeral port.
        class _H(BaseHTTPRequestHandler):
            def do_HEAD(self):  # noqa: N802
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args, **kwargs):  # silence
                return

        httpd = HTTPServer(("127.0.0.1", 0), _H)
        port = httpd.server_address[1]
        thread = Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            cfg = _make_config(_codex())
            snap = self._snap(snapshot_base_url=f"http://127.0.0.1:{port}/")
            result = probe_snapshot(snap, config=cfg, timeout=1.0)
            self.assertTrue(result.ok, [c.message for c in result.checks])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_probe_profile_reuses_snapshot_health_logic(self) -> None:
        from cairn.dispatcher.ai_health import probe_profile
        from cairn.server.models import AiProfile

        cfg = _make_config(_codex())
        profile = AiProfile(
            id="ai_test",
            name="p",
            description="",
            worker_type="codex",
            provider="",
            base_url="",
            model="m",
            api_key_env="CAIRN_TEST_KEY_PRESENT",
            available=True,
            detail="",
            healthcheck_timeout=1.0,
            model_reasoning_effort=None,
            warnings=[],
            seeded_from_worker=None,
            last_health_ok=None,
            last_health_message="",
            last_health_at=None,
            models=["m"],
            created_at="2026-06-09T00:00:00Z",
            updated_at="2026-06-09T00:00:00Z",
        )
        result = probe_profile(profile, config=cfg)
        self.assertTrue(result.ok, [c.message for c in result.checks])
        self.assertEqual(
            {c.name for c in result.checks},
            {"api_key_env_present", "base_url_reachable", "worker_type_declared"},
        )

    def test_profile_worker_healthcheck_uses_profile_overlay(self) -> None:
        from cairn.dispatcher.ai_health import run_profile_worker_healthcheck
        from cairn.dispatcher.runtime.process import ProcessResult
        from cairn.dispatcher.tasks.common import HealthcheckRun
        from cairn.server.models import AiProfile

        class _H(BaseHTTPRequestHandler):
            def do_HEAD(self):  # noqa: N802
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args, **kwargs):  # silence
                return

        httpd = HTTPServer(("127.0.0.1", 0), _H)
        port = httpd.server_address[1]
        thread = Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        profile_base_url = f"http://127.0.0.1:{port}/v1"
        cfg = _make_config(_codex(model="base-model", base_url="https://base.example/v1", api_key="base-key"))
        profile = AiProfile(
            id="ai_test",
            name="p",
            description="",
            worker_type="codex",
            provider="",
            base_url=profile_base_url,
            model="profile-model",
            api_key_env="OPENAI_API_KEY",
            available=True,
            detail="",
            healthcheck_timeout=2.0,
            model_reasoning_effort=None,
            warnings=[],
            seeded_from_worker=None,
            last_health_ok=None,
            last_health_message="",
            last_health_at=None,
            models=["profile-model"],
            created_at="2026-06-09T00:00:00Z",
            updated_at="2026-06-09T00:00:00Z",
        )
        captured = {}

        class _ContainerManager:
            removed = False

            def create_startup_container(self):
                return "startup-container"

            def remove_container(self, container_name, force=False):
                self.removed = container_name == "startup-container" and force

        def fake_run_healthcheck(container_manager, container_name, worker, command, *, timeout_seconds, tty):
            captured["container_name"] = container_name
            captured["env"] = dict(worker.env)
            captured["command"] = list(command)
            captured["timeout_seconds"] = timeout_seconds
            captured["tty"] = tty
            return HealthcheckRun(ProcessResult(returncode=0, stdout="pong\n", stderr=""), duration_ms=42)

        cm = _ContainerManager()
        try:
            with patch("cairn.dispatcher.ai_health.run_healthcheck", fake_run_healthcheck):
                result = run_profile_worker_healthcheck(
                    profile,
                    config=cfg,
                    container_manager=cm,
                    cached_secret="profile-secret",
                    timeout_seconds=3,
                )
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

        self.assertTrue(result.ok, result.message)
        self.assertEqual(captured["env"]["CODEX_MODEL"], "profile-model")
        self.assertEqual(captured["env"]["CODEX_BASE_URL"], profile_base_url)
        self.assertEqual(captured["env"]["OPENAI_API_KEY"], "profile-secret")
        self.assertIn("profile-model", captured["command"])
        self.assertEqual(captured["timeout_seconds"], 3)
        self.assertTrue(captured["tty"])
        self.assertTrue(cm.removed)

    def test_profile_worker_healthcheck_defaults_to_runtime_timeout(self) -> None:
        from cairn.dispatcher.ai_health import run_profile_worker_healthcheck
        from cairn.dispatcher.runtime.process import ProcessResult
        from cairn.dispatcher.tasks.common import HealthcheckRun
        from cairn.server.models import AiProfile

        cfg = _make_config(_codex())
        cfg.runtime.healthcheck_timeout = 7
        profile = AiProfile(
            id="ai_test",
            name="p",
            description="",
            worker_type="codex",
            provider="",
            base_url="",
            model="m",
            api_key_env="OPENAI_API_KEY",
            available=True,
            detail="",
            healthcheck_timeout=1.0,
            model_reasoning_effort=None,
            warnings=[],
            seeded_from_worker=None,
            last_health_ok=None,
            last_health_message="",
            last_health_at=None,
            models=["m"],
            created_at="2026-06-09T00:00:00Z",
            updated_at="2026-06-09T00:00:00Z",
        )
        captured = {}

        class _ContainerManager:
            def create_startup_container(self):
                return "startup-container"

            def remove_container(self, container_name, force=False):
                return None

        def fake_run_healthcheck(*args, **kwargs):
            captured["timeout_seconds"] = kwargs["timeout_seconds"]
            return HealthcheckRun(ProcessResult(returncode=0, stdout="pong", stderr=""), duration_ms=10)

        with patch("cairn.dispatcher.ai_health.run_healthcheck", fake_run_healthcheck):
            result = run_profile_worker_healthcheck(
                profile,
                config=cfg,
                container_manager=_ContainerManager(),
                cached_secret="profile-secret",
            )

        self.assertTrue(result.ok, result.message)
        self.assertEqual(captured["timeout_seconds"], 7)

    def test_profile_worker_healthcheck_failure_message_is_actionable(self) -> None:
        from cairn.dispatcher.ai_health import run_profile_worker_healthcheck
        from cairn.dispatcher.runtime.process import ProcessResult
        from cairn.dispatcher.tasks.common import HealthcheckRun
        from cairn.server.models import AiProfile

        cfg = _make_config(_codex())
        profile = AiProfile(
            id="ai_test",
            name="p",
            description="",
            worker_type="codex",
            provider="",
            base_url="",
            model="m",
            api_key_env="OPENAI_API_KEY",
            available=True,
            detail="",
            healthcheck_timeout=1.0,
            model_reasoning_effort=None,
            warnings=[],
            seeded_from_worker=None,
            last_health_ok=None,
            last_health_message="",
            last_health_at=None,
            models=["m"],
            created_at="2026-06-09T00:00:00Z",
            updated_at="2026-06-09T00:00:00Z",
        )

        class _ContainerManager:
            def create_startup_container(self):
                return "startup-container"

            def remove_container(self, container_name, force=False):
                return None

        def fake_run_healthcheck(*args, **kwargs):
            return HealthcheckRun(
                ProcessResult(returncode=124, stdout="", stderr="request timed out", timed_out=True),
                duration_ms=1001,
            )

        with patch("cairn.dispatcher.ai_health.run_healthcheck", fake_run_healthcheck):
            result = run_profile_worker_healthcheck(
                profile,
                config=cfg,
                container_manager=_ContainerManager(),
                cached_secret="profile-secret",
                timeout_seconds=1,
            )

        self.assertFalse(result.ok)
        self.assertIn("code=124", result.message)
        self.assertIn("duration_ms=1001", result.message)
        self.assertIn("timed_out=true", result.message)
        self.assertIn("stderr=request timed out", result.message)


class DispatcherTaskAiSelectionTests(unittest.TestCase):
    def test_project_ai_snapshots_are_task_specific(self) -> None:
        from cairn.dispatcher.scheduler.loop import DispatcherLoop
        from cairn.dispatcher.scheduler.project_cache import ProjectCaches
        from cairn.server.models import ProjectAiProfileSnapshot

        loop = DispatcherLoop.__new__(DispatcherLoop)
        loop.project_caches = ProjectCaches()
        loop.project_caches.ai_chains = {
            "proj": {
                "bootstrap": [
                    ProjectAiProfileSnapshot(
                        profile_id="boot", task_type="bootstrap", role="primary", position=0,
                        snapshot_name="boot", snapshot_worker_type="codex",
                        snapshot_model="m1", snapshot_api_key_env="K1",
                    )
                ],
                "explore": [
                    ProjectAiProfileSnapshot(
                        profile_id="intent", task_type="explore", role="primary", position=0,
                        snapshot_name="intent", snapshot_worker_type="codex",
                        snapshot_model="m2", snapshot_api_key_env="K2",
                    )
                ],
                "reason": [
                    ProjectAiProfileSnapshot(
                        profile_id="reason", task_type="reason", role="primary", position=0,
                        snapshot_name="reason", snapshot_worker_type="claudecode",
                        snapshot_model="m3", snapshot_api_key_env="K3",
                    )
                ],
            }
        }

        self.assertEqual(loop._project_ai_snapshots("proj", "bootstrap")[0].profile_id, "boot")
        self.assertEqual(loop._project_ai_snapshots("proj", "explore")[0].profile_id, "intent")
        self.assertEqual(loop._project_ai_snapshots("proj", "reason")[0].profile_id, "reason")
        self.assertEqual(loop._project_ai_snapshots("proj", "unknown"), [])


class ProfileWarningsTests(unittest.TestCase):
    def test_warnings_for_non_canonical_auth(self) -> None:
        from cairn.dispatcher.ai_health import profile_warnings
        warnings = profile_warnings("codex", "DEEPSEEK_KEY")
        self.assertEqual(len(warnings), 1)
        self.assertIn("OPENAI_API_KEY", warnings[0])

    def test_no_warnings_for_canonical(self) -> None:
        from cairn.dispatcher.ai_health import profile_warnings
        self.assertEqual(profile_warnings("codex", "OPENAI_API_KEY"), [])
        self.assertEqual(profile_warnings("claudecode", "ANTHROPIC_AUTH_TOKEN"), [])


class SyncPayloadTests(unittest.TestCase):
    def test_worker_models_are_trimmed_and_deduplicated(self) -> None:
        from cairn.dispatcher.config import WorkerConfig

        worker = WorkerConfig(
            name="x",
            type="codex",
            task_types=["bootstrap"],
            max_running=1,
            priority=0,
            models=[" gpt-large ", "gpt-reason", "gpt-large"],
            env={"CODEX_MODEL": "gpt-default", "CODEX_BASE_URL": "u", "OPENAI_API_KEY": "k"},
        )

        self.assertEqual(worker.models, ["gpt-large", "gpt-reason"])

    def test_worker_models_reject_empty_values(self) -> None:
        from pydantic import ValidationError
        from cairn.dispatcher.config import WorkerConfig

        with self.assertRaises(ValidationError):
            WorkerConfig(
                name="x",
                type="codex",
                task_types=["bootstrap"],
                max_running=1,
                priority=0,
                models=["gpt-large", "  "],
                env={"CODEX_MODEL": "gpt-default", "CODEX_BASE_URL": "u", "OPENAI_API_KEY": "k"},
            )

    def test_supported_workers_only(self) -> None:
        from cairn.dispatcher.config import WorkerConfig
        pi = WorkerConfig(
            name="pi_x", type="pi", task_types=["bootstrap"],
            max_running=1, priority=0,
            env={"PI_MODEL": "m", "PI_BASE_URL": "u", "PI_API_KEY": "k", "PI_PROVIDER_API": "openai-completions"},
        )
        # Instantiate a stub loop with the config so we can call its helper.
        from cairn.dispatcher.scheduler.loop import DispatcherLoop
        from cairn.dispatcher.config import (
            RuntimeConfig, TasksConfig, ContainerConfig, DispatchConfig,
            BootstrapTaskConfig, ReasonTaskConfig, ExploreTaskConfig,
        )
        runtime = RuntimeConfig(
            interval=1, max_workers=1, max_project_workers=1,
            max_running_projects=1, healthcheck_timeout=1, prompt_group="g",
        )
        tasks = TasksConfig(
            bootstrap=BootstrapTaskConfig(timeout=5, conclude_timeout=5),
            reason=ReasonTaskConfig(timeout=5, max_intents=3),
            explore=ExploreTaskConfig(timeout=5, conclude_timeout=5),
        )
        container = ContainerConfig(
            image="cairn/test:latest", user=None, network_mode="cairn",
            completed_action="stop",
        )
        cfg = DispatchConfig(
            server="http://localhost", runtime=runtime, tasks=tasks,
            container=container, workers=[pi],
        )
        # Bypass __init__ so we can test the helper without a real container manager.
        loop = DispatcherLoop.__new__(DispatcherLoop)
        loop.config = cfg
        payload = loop._build_ai_sync_payload()
        self.assertEqual(payload, [])

    def test_supported_translation(self) -> None:
        from cairn.dispatcher.scheduler.loop import DispatcherLoop
        from cairn.dispatcher.config import (
            DispatchConfig, RuntimeConfig, TasksConfig, ContainerConfig,
            BootstrapTaskConfig, ReasonTaskConfig, ExploreTaskConfig,
        )
        runtime = RuntimeConfig(interval=1, max_workers=1, max_project_workers=1, max_running_projects=1, healthcheck_timeout=1, prompt_group="g")
        tasks = TasksConfig(
            bootstrap=BootstrapTaskConfig(timeout=5, conclude_timeout=5),
            reason=ReasonTaskConfig(timeout=5, max_intents=3),
            explore=ExploreTaskConfig(timeout=5, conclude_timeout=5),
        )
        container = ContainerConfig(
            image="cairn/test:latest", user=None, network_mode="cairn",
            completed_action="stop",
        )
        cfg = DispatchConfig(
            server="http://localhost", runtime=runtime, tasks=tasks,
            container=container,
            workers=[
                _claudecode(name="claude_deepseek", model="ds-v4",
                            base_url="https://api.deepseek.com/anthropic",
                            api_key="ANTHROPIC_AUTH_TOKEN"),
                _codex(name="codex_default", model="gpt-5.4-mini",
                       base_url="https://seuapi.20250731.xyz", api_key="OPENAI_API_KEY"),
            ],
        )
        loop = DispatcherLoop.__new__(DispatcherLoop)
        loop.config = cfg
        payload = loop._build_ai_sync_payload()
        names = {p["name"] for p in payload}
        self.assertEqual(names, {"claude_deepseek", "codex_default"})
        claude = next(p for p in payload if p["name"] == "claude_deepseek")
        self.assertEqual(claude["worker_type"], "claudecode")
        self.assertEqual(claude["model"], "ds-v4")
        self.assertEqual(claude["base_url"], "https://api.deepseek.com/anthropic")
        self.assertEqual(claude["api_key_env"], "ANTHROPIC_AUTH_TOKEN")
        codex = next(p for p in payload if p["name"] == "codex_default")
        self.assertEqual(codex["worker_type"], "codex")
        self.assertEqual(codex["api_key_env"], "OPENAI_API_KEY")

    def test_multiple_worker_models_stay_on_single_seeded_profile(self) -> None:
        from cairn.dispatcher.scheduler.loop import DispatcherLoop

        loop = DispatcherLoop.__new__(DispatcherLoop)
        loop.config = _make_config(
            _codex(
                name="codex",
                model="gpt-default",
                models=["gpt-default", "gpt-large"],
                model_reasoning_effort="xhigh",
            )
        )

        payload = loop._build_ai_sync_payload()

        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["name"], "codex")
        self.assertEqual(payload[0]["model"], "gpt-default")
        self.assertEqual(payload[0]["models"], ["gpt-default", "gpt-large"])
        self.assertEqual(payload[0]["model_reasoning_effort"], "xhigh")

    def test_env_default_model_is_first_even_when_not_listed(self) -> None:
        from cairn.dispatcher.scheduler.loop import DispatcherLoop

        loop = DispatcherLoop.__new__(DispatcherLoop)
        loop.config = _make_config(
            _codex(
                name="codex",
                model="gpt-default",
                models=["gpt-large"],
            )
        )

        payload = loop._build_ai_sync_payload()

        self.assertEqual([item["name"] for item in payload], ["codex"])
        self.assertEqual([item["model"] for item in payload], ["gpt-default"])
        self.assertEqual(payload[0]["models"], ["gpt-default", "gpt-large"])

    def test_single_model_keeps_legacy_seed_name(self) -> None:
        from cairn.dispatcher.scheduler.loop import DispatcherLoop

        loop = DispatcherLoop.__new__(DispatcherLoop)
        loop.config = _make_config(_codex(name="codex", model="gpt-default"))

        payload = loop._build_ai_sync_payload()

        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["name"], "codex")
        self.assertEqual(payload[0]["model"], "gpt-default")

    def test_runtime_env_names_are_canonical(self) -> None:
        from cairn.dispatcher.scheduler.loop import DispatcherLoop
        from cairn.dispatcher.config import (
            DispatchConfig, RuntimeConfig, TasksConfig, ContainerConfig,
            BootstrapTaskConfig, ReasonTaskConfig, ExploreTaskConfig,
        )
        runtime = RuntimeConfig(interval=1, max_workers=1, max_project_workers=1, max_running_projects=1, healthcheck_timeout=1, prompt_group="g")
        tasks = TasksConfig(
            bootstrap=BootstrapTaskConfig(timeout=5, conclude_timeout=5),
            reason=ReasonTaskConfig(timeout=5, max_intents=3),
            explore=ExploreTaskConfig(timeout=5, conclude_timeout=5),
        )
        container = ContainerConfig(
            image="cairn/test:latest", user=None, network_mode="cairn",
            completed_action="stop",
        )
        cfg = DispatchConfig(
            server="http://localhost", runtime=runtime, tasks=tasks,
            container=container,
            workers=[
                _claudecode(
                    name="claude_canonical",
                    model="ds-v4",
                    base_url="https://api.deepseek.com/anthropic",
                    api_key="runtime-token-value",
                ),
            ],
        )
        loop = DispatcherLoop.__new__(DispatcherLoop)
        loop.config = cfg
        payload = loop._build_ai_sync_payload()
        self.assertEqual(payload[0]["api_key_env"], "ANTHROPIC_AUTH_TOKEN")

    def test_ai_catalog_sync_does_not_fetch_or_report_remote_models(self) -> None:
        from cairn.dispatcher.scheduler.loop import DispatcherLoop
        from cairn.dispatcher.config import (
            DispatchConfig, RuntimeConfig, TasksConfig, ContainerConfig,
            BootstrapTaskConfig, ReasonTaskConfig, ExploreTaskConfig,
        )

        class Result:
            ok = True
            status_code = 200
            text = ""

            def __init__(self, data):
                self.data = data

        class Client:
            def __init__(self):
                self.models_report_calls = 0
                self.health_report_calls = 0

            def list_ai_profiles(self):
                return Result([])

            def sync_ai_profiles(self, body):
                return Result([
                    {
                        "id": "ai_codex",
                        "worker_type": "codex",
                        "base_url": "",
                        "api_key_env": "OPENAI_API_KEY",
                        "model": "gpt-manual",
                        "healthcheck_timeout": 0.1,
                    }
                ])

            def post_ai_health_report(self, body):
                self.health_report_calls += 1
                return Result(None)

            def post_ai_models_report(self, body):
                self.models_report_calls += 1
                return Result(None)

        runtime = RuntimeConfig(interval=1, max_workers=1, max_project_workers=1, max_running_projects=1, healthcheck_timeout=1, prompt_group="g")
        tasks = TasksConfig(
            bootstrap=BootstrapTaskConfig(timeout=5, conclude_timeout=5),
            reason=ReasonTaskConfig(timeout=5, max_intents=3),
            explore=ExploreTaskConfig(timeout=5, conclude_timeout=5),
        )
        cfg = DispatchConfig(
            server="http://localhost",
            runtime=runtime,
            tasks=tasks,
            container=ContainerConfig(image="cairn/test:latest", user=None, network_mode="cairn", completed_action="stop"),
            workers=[_codex(model="gpt-manual")],
        )
        loop = DispatcherLoop.__new__(DispatcherLoop)
        loop.config = cfg
        loop.client = Client()

        loop._sync_ai_catalog_from_dispatch_yaml()

        self.assertEqual(loop.client.health_report_calls, 1)
        self.assertEqual(loop.client.models_report_calls, 0)

    def test_ai_catalog_sync_runs_even_when_profiles_exist(self) -> None:
        from cairn.dispatcher.scheduler.loop import DispatcherLoop

        class Result:
            ok = True
            status_code = 200
            text = ""

            def __init__(self, data):
                self.data = data

        class Client:
            def __init__(self):
                self.sync_calls = 0
                self.sync_body = None
                self.health_report_calls = 0

            def list_ai_profiles(self):
                return Result([
                    {
                        "id": "ai_existing",
                        "worker_type": "codex",
                        "base_url": "",
                        "api_key_env": "OPENAI_API_KEY",
                        "model": "gpt-old",
                        "healthcheck_timeout": 0.1,
                    }
                ])

            def sync_ai_profiles(self, body):
                self.sync_calls += 1
                self.sync_body = body
                return Result([
                    {
                        "id": "ai_codex",
                        "worker_type": "codex",
                        "base_url": "",
                        "api_key_env": "OPENAI_API_KEY",
                        "model": "gpt-default",
                        "healthcheck_timeout": 0.1,
                    }
                ])

            def post_ai_health_report(self, body):
                self.health_report_calls += 1
                return Result(None)

        loop = DispatcherLoop.__new__(DispatcherLoop)
        loop.config = _make_config(
            _codex(name="codex", model="gpt-default", models=["gpt-large"])
        )
        loop.client = Client()

        loop._sync_ai_catalog_from_dispatch_yaml()

        self.assertEqual(loop.client.sync_calls, 1)
        self.assertEqual(
            [item["name"] for item in loop.client.sync_body["workers"]],
            ["codex"],
        )
        self.assertEqual(loop.client.sync_body["workers"][0]["models"], ["gpt-default", "gpt-large"])
        self.assertEqual(loop.client.health_report_calls, 1)


class AiProfileDbBridgeTests(unittest.TestCase):
    """End-to-end persistence: sync upserts, idempotent, health-report flips availability."""

    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        from cairn.server import db
        db._db_path = None
        db.configure(Path(self.tmp.name))
        self.db = db

    def tearDown(self) -> None:
        self.db._db_path = None
        os.unlink(self.tmp.name)

    def test_sync_upsert_idempotent(self) -> None:
        from cairn.server.routers.ai_profiles import (
            list_ai_profiles, sync_ai_profiles, post_health_report,
        )
        from cairn.server.models import (
            AiProfileSyncRequest, AiProfileSyncWorker,
        )

        body = AiProfileSyncRequest(workers=[
            AiProfileSyncWorker(name="claude_ds", worker_type="claudecode",
                                model="ds-v4", base_url="https://api.deepseek.com/anthropic",
                                api_key_env="ANTHROPIC_AUTH_TOKEN"),
            AiProfileSyncWorker(name="codex_default", worker_type="codex",
                                model="gpt-5.4", base_url="",
                                api_key_env="OPENAI_API_KEY"),
        ])
        result1 = sync_ai_profiles(body)
        self.assertEqual(len(result1), 2)
        ids_after_first = {p.id for p in result1}

        # Re-sync with the same content; ids must match (idempotent).
        result2 = sync_ai_profiles(body)
        ids_after_second = {p.id for p in result2}
        self.assertEqual(ids_after_first, ids_after_second)

        # Sync with one worker removed; the removed worker's seeded row is
        # pruned, leaving only the supported worker plus any operator-created
        # profiles.
        body2 = AiProfileSyncRequest(workers=[
            AiProfileSyncWorker(name="claude_ds", worker_type="claudecode",
                                model="ds-v4", base_url="https://api.deepseek.com/anthropic",
                                api_key_env="ANTHROPIC_AUTH_TOKEN"),
        ])
        result3 = sync_ai_profiles(body2)
        self.assertEqual(len(result3), 1)
        self.assertEqual({p.name for p in result3}, {"claude_ds"})

    def test_sync_updates_profile_models_and_reasoning(self) -> None:
        from cairn.server.routers.ai_profiles import sync_ai_profiles
        from cairn.server.models import AiProfileSyncRequest, AiProfileSyncWorker

        body = AiProfileSyncRequest(workers=[
            AiProfileSyncWorker(
                name="codex",
                worker_type="codex",
                model="gpt-default",
                models=["gpt-large", "gpt-default"],
                base_url="",
                api_key_env="OPENAI_API_KEY",
                model_reasoning_effort="xhigh",
            ),
        ])

        result = sync_ai_profiles(body)
        profile = next(item for item in result if item.seeded_from_worker == "codex")
        self.assertEqual(profile.model, "gpt-default")
        self.assertEqual(profile.models, ["gpt-default", "gpt-large"])
        self.assertEqual(profile.model_reasoning_effort, "xhigh")

    def test_sync_drops_unsupported_worker_types(self) -> None:
        from cairn.server.routers.ai_profiles import sync_ai_profiles
        from cairn.server.models import AiProfileSyncRequest, AiProfileSyncWorker

        body = AiProfileSyncRequest(workers=[
            AiProfileSyncWorker(name="claude_ds", worker_type="claudecode",
                                model="ds-v4", base_url="",
                                api_key_env="ANTHROPIC_AUTH_TOKEN"),
            AiProfileSyncWorker(name="pi_x", worker_type="pi",
                                model="m", base_url="",
                                api_key_env="PI_API_KEY"),
        ])
        result = sync_ai_profiles(body)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "claude_ds")

    def test_sync_prunes_obsolete_seeded_profiles(self) -> None:
        """Workers removed from dispatch.yaml must be pruned by sync.

        Pre-seeds an obsolete ``codex:gpt-5.4`` row the way an older
        dispatcher would have written it, then syncs the current
        ``codex``/``claudecode`` worker set and confirms the obsolete
        row (and its models) are deleted.
        """
        from cairn.server.routers.ai_profiles import (
            list_ai_profiles, sync_ai_profiles,
        )
        from cairn.server.models import AiProfileSyncRequest, AiProfileSyncWorker

        # Pre-seed an obsolete seeded profile as if a previous dispatcher
        # version had inserted it. seeded_from_worker != current worker name.
        now = "2026-06-05T00:00:00Z"
        with self.db.get_conn() as conn:
            conn.execute(
                """
                INSERT INTO ai_profiles (
                    id, name, worker_type, provider, base_url,
                    model, api_key_env, available, detail,
                    healthcheck_timeout, seeded_from_worker,
                    created_at, updated_at
                ) VALUES (?, ?, 'codex', '', '', 'gpt-5.4', 'OPENAI_API_KEY', 1, '', 1.0, ?, ?, ?)
                """,
                ("ai_seed_codex_gpt-5_4", "codex:gpt-5.4", "codex:gpt-5.4", now, now),
            )
            conn.execute(
                "INSERT INTO ai_profile_models (profile_id, model, updated_at) VALUES (?, ?, ?)",
                ("ai_seed_codex_gpt-5_4", "gpt-5.4", now),
            )
            conn.commit()

        body = AiProfileSyncRequest(workers=[
            AiProfileSyncWorker(name="codex", worker_type="codex",
                                model="gpt-5.4", base_url="",
                                api_key_env="OPENAI_API_KEY",
                                models=["gpt-5.4-mini", "gpt-5.4", "gpt-5.5"]),
            AiProfileSyncWorker(name="claudecode", worker_type="claudecode",
                                model="deepseek-v4-pro", base_url="",
                                api_key_env="ANTHROPIC_AUTH_TOKEN"),
        ])
        result = sync_ai_profiles(body)
        ids = {p.id for p in result}
        self.assertIn("ai_seed_codex", ids)
        self.assertIn("ai_seed_claudecode", ids)
        self.assertNotIn("ai_seed_codex_gpt-5_4", ids)

        # Confirm the obsolete row and its models are gone.
        with self.db.get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM ai_profiles WHERE id = ? OR seeded_from_worker = ?",
                ("ai_seed_codex_gpt-5_4", "codex:gpt-5.4"),
            ).fetchone()
            self.assertIsNone(row)
            model_rows = conn.execute(
                "SELECT model FROM ai_profile_models WHERE profile_id = ?",
                ("ai_seed_codex_gpt-5_4",),
            ).fetchall()
            self.assertEqual(model_rows, [])

    def test_sync_preserves_operator_created_profiles(self) -> None:
        """Profiles with seeded_from_worker IS NULL must survive a sync prune."""
        from cairn.server.routers.ai_profiles import (
            create_ai_profile, list_ai_profiles, sync_ai_profiles,
        )
        from cairn.server.models import (
            AiProfileCreate, AiProfileSyncRequest, AiProfileSyncWorker,
        )

        manual = create_ai_profile(AiProfileCreate(
            name="manual", worker_type="codex", model="gpt-manual",
            api_key_env="OPENAI_API_KEY",
        ))
        self.assertIsNone(manual.seeded_from_worker)

        # Sync with a payload that does not include the manual worker.
        body = AiProfileSyncRequest(workers=[
            AiProfileSyncWorker(name="codex", worker_type="codex",
                                model="gpt-5.4", base_url="",
                                api_key_env="OPENAI_API_KEY"),
        ])
        sync_ai_profiles(body)

        listed = list_ai_profiles()
        ids = {p.id for p in listed}
        self.assertIn(manual.id, ids)
        self.assertIn("ai_seed_codex", ids)

    def test_sync_with_no_supported_workers_drops_all_seeded(self) -> None:
        """An empty/payload with only unsupported workers prunes every seeded row."""
        from cairn.server.routers.ai_profiles import (
            list_ai_profiles, sync_ai_profiles,
        )
        from cairn.server.models import AiProfileSyncRequest, AiProfileSyncWorker

        # Seed two profiles manually.
        body = AiProfileSyncRequest(workers=[
            AiProfileSyncWorker(name="codex", worker_type="codex",
                                model="gpt-5.4", base_url="",
                                api_key_env="OPENAI_API_KEY"),
            AiProfileSyncWorker(name="claudecode", worker_type="claudecode",
                                model="ds-v4", base_url="",
                                api_key_env="ANTHROPIC_AUTH_TOKEN"),
        ])
        sync_ai_profiles(body)
        self.assertEqual(len(list_ai_profiles()), 2)

        # Re-sync with only an unsupported worker. The supported workers are
        # no longer "active" so their seeded rows must be pruned.
        body2 = AiProfileSyncRequest(workers=[
            AiProfileSyncWorker(name="pi_x", worker_type="pi",
                                model="m", base_url="",
                                api_key_env="PI_API_KEY"),
        ])
        sync_ai_profiles(body2)
        self.assertEqual(len(list_ai_profiles()), 0)

    def test_sync_keeps_seeded_profile_whose_worker_renamed_to_match(self) -> None:
        """A worker renaming its seed must adopt the old id, not duplicate it."""
        from cairn.server.routers.ai_profiles import (
            list_ai_profiles, sync_ai_profiles,
        )
        from cairn.server.models import AiProfileSyncRequest, AiProfileSyncWorker

        # First sync establishes the "codex" seeded row.
        body = AiProfileSyncRequest(workers=[
            AiProfileSyncWorker(name="codex", worker_type="codex",
                                model="gpt-5.4", base_url="",
                                api_key_env="OPENAI_API_KEY"),
        ])
        sync_ai_profiles(body)
        self.assertEqual(len(list_ai_profiles()), 1)
        first_id = list_ai_profiles()[0].id

        # Second sync: the new payload still has a worker named "codex"
        # so the row is updated in place; the id must stay stable.
        body2 = AiProfileSyncRequest(workers=[
            AiProfileSyncWorker(name="codex", worker_type="codex",
                                model="gpt-5.4", base_url="",
                                api_key_env="OPENAI_API_KEY",
                                models=["gpt-5.4", "gpt-5.4-mini"]),
        ])
        listed = sync_ai_profiles(body2)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].id, first_id)

    def test_health_report_flips_availability(self) -> None:
        from cairn.server.routers.ai_profiles import (
            create_ai_profile, post_health_report, list_ai_profiles,
        )
        from cairn.server.models import (
            AiProfileCreate, AiProfileHealthReportRequest, AiProfileHealthReport,
        )

        created = create_ai_profile(AiProfileCreate(
            name="p", worker_type="codex", model="m", api_key_env="OPENAI_API_KEY",
        ))
        # Initially available=True; mark unhealthy.
        post_health_report(AiProfileHealthReportRequest(reports=[
            AiProfileHealthReport(profile_id=created.id, ok=False, message="env not set"),
        ]))
        listed = list_ai_profiles()
        row = next(p for p in listed if p.id == created.id)
        self.assertFalse(row.available)
        self.assertEqual(row.last_health_message, "env not set")
        self.assertFalse(row.last_health_ok)
        self.assertIsNotNone(row.last_health_at)

        # Mark healthy again.
        post_health_report(AiProfileHealthReportRequest(reports=[
            AiProfileHealthReport(profile_id=created.id, ok=True, message="ok"),
        ]))
        listed = list_ai_profiles()
        row = next(p for p in listed if p.id == created.id)
        self.assertTrue(row.available)
        self.assertTrue(row.last_health_ok)

    def test_auth_var_is_canonicalized_on_create(self) -> None:
        from cairn.server.routers.ai_profiles import create_ai_profile
        from cairn.server.models import AiProfileCreate

        created = create_ai_profile(AiProfileCreate(
            name="p", worker_type="codex", model="m", api_key_env="DEEPSEEK_KEY",
        ))
        self.assertEqual(created.api_key_env, "OPENAI_API_KEY")
        self.assertEqual(created.warnings, [])

    def test_update_keeps_canonical_auth_env(self) -> None:
        from cairn.server.routers.ai_profiles import create_ai_profile, update_ai_profile
        from cairn.server.models import AiProfileCreate, AiProfileUpdate

        created = create_ai_profile(AiProfileCreate(
            name="p", worker_type="codex", model="m", api_key_env="DEEPSEEK_KEY",
        ))
        updated = update_ai_profile(
            created.id, AiProfileUpdate(api_key_env="DEEPSEEK_KEY"),
        )
        self.assertEqual(updated.api_key_env, "OPENAI_API_KEY")
        self.assertEqual(updated.warnings, [])

    def test_healthcheck_timeout_bounds(self) -> None:
        from pydantic import ValidationError
        from cairn.server.models import AiProfileCreate

        with self.assertRaises(ValidationError):
            AiProfileCreate(name="x", worker_type="codex", model="m",
                            api_key_env="K", healthcheck_timeout=0)
        with self.assertRaises(ValidationError):
            AiProfileCreate(name="x", worker_type="codex", model="m",
                            api_key_env="K", healthcheck_timeout=100.0)
        ok = AiProfileCreate(name="x", worker_type="codex", model="m",
                             api_key_env="K", healthcheck_timeout=2.5)
        self.assertEqual(ok.healthcheck_timeout, 2.5)

    def test_check_request_lifecycle(self) -> None:
        from cairn.server.routers.ai_profiles import (
            claim_ai_profile_check_request,
            complete_ai_profile_check_request,
            create_ai_profile,
            trigger_ai_profile_check,
        )
        from cairn.server.models import AiProfileCheckCompleteRequest, AiProfileCreate

        created = create_ai_profile(AiProfileCreate(
            name="p", worker_type="codex", model="m", api_key_env="OPENAI_API_KEY",
        ))
        queued = trigger_ai_profile_check(created.id, user=None)
        self.assertEqual(queued.status, "pending")

        claimed = claim_ai_profile_check_request()
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertEqual(claimed.profile_id, created.id)
        self.assertEqual(claimed.status, "running")

        complete_ai_profile_check_request(
            claimed.id,
            AiProfileCheckCompleteRequest(ok=True, message="ok"),
        )


if __name__ == "__main__":
    unittest.main()
