"""Bridge + health check tests for the AI profile system."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

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


def _claudecode(name="c1", model="m", base_url="https://api.example/anthropic", api_key="K", env_overrides=None):
    from cairn.dispatcher.config import WorkerConfig
    env = {"ANTHROPIC_MODEL": model, "ANTHROPIC_BASE_URL": base_url, "ANTHROPIC_AUTH_TOKEN": api_key}
    if env_overrides:
        env.update(env_overrides)
    return WorkerConfig(
        name=name, type="claudecode", task_types=["bootstrap"],
        max_running=1, priority=0, env=env,
    )


def _codex(name="x1", model="m", base_url="https://api.example/v1", api_key="K"):
    from cairn.dispatcher.config import WorkerConfig
    return WorkerConfig(
        name=name, type="codex", task_types=["bootstrap"],
        max_running=1, priority=0,
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
            profile_id="p1", role="primary", position=0,
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
            thread.join(timeout=2)


class DispatcherTaskAiSelectionTests(unittest.TestCase):
    def test_project_ai_snapshots_are_task_specific(self) -> None:
        from cairn.dispatcher.scheduler.loop import DispatcherLoop
        from cairn.server.models import ProjectAiProfileSnapshot

        loop = DispatcherLoop.__new__(DispatcherLoop)
        loop._project_ai_cache = {
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

        # Sync with one worker removed; the remaining row stays.
        body2 = AiProfileSyncRequest(workers=[
            AiProfileSyncWorker(name="claude_ds", worker_type="claudecode",
                                model="ds-v4", base_url="https://api.deepseek.com/anthropic",
                                api_key_env="ANTHROPIC_AUTH_TOKEN"),
        ])
        result3 = sync_ai_profiles(body2)
        self.assertEqual(len(result3), 2)  # we don't auto-delete

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

    def test_auth_var_warning_on_create(self) -> None:
        from cairn.server.routers.ai_profiles import create_ai_profile
        from cairn.server.models import AiProfileCreate

        created = create_ai_profile(AiProfileCreate(
            name="p", worker_type="codex", model="m", api_key_env="DEEPSEEK_KEY",
        ))
        self.assertEqual(len(created.warnings), 1)
        self.assertIn("OPENAI_API_KEY", created.warnings[0])

    def test_canonical_auth_clears_warning(self) -> None:
        from cairn.server.routers.ai_profiles import create_ai_profile, update_ai_profile
        from cairn.server.models import AiProfileCreate, AiProfileUpdate

        created = create_ai_profile(AiProfileCreate(
            name="p", worker_type="codex", model="m", api_key_env="DEEPSEEK_KEY",
        ))
        self.assertEqual(len(created.warnings), 1)
        updated = update_ai_profile(
            created.id, AiProfileUpdate(api_key_env="OPENAI_API_KEY"),
        )
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


if __name__ == "__main__":
    unittest.main()
