"""Tests for the system-config admin endpoints.

Covers GET/PUT round-trips on:
- /runtime-limits (max_workers, interval, prompt_group, etc.)
- /task-timeouts (bootstrap/explore/reason lease timeouts)
- /observability (record flags, byte caps, retention, redaction)
- /server-log-retention (log level/format, retention loop)

Also covers:
- Validation rejection: max_project_workers > max_workers
- Observability record-set ↔ boolean-flag translation
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


# ---------------------------------------------------------------------------
# ContainerConfig schema
# ---------------------------------------------------------------------------


class ContainerConfigSchemaTests(unittest.TestCase):
    def test_nano_cpus_optional(self) -> None:
        from cairn.shared.config.worker_models import ContainerConfig

        c = ContainerConfig(image="img", network_mode="net", completed_action="stop")
        self.assertIsNone(c.nano_cpus)

    def test_nano_cpus_present(self) -> None:
        from cairn.shared.config.worker_models import ContainerConfig

        c = ContainerConfig(image="img", network_mode="net", completed_action="stop", nano_cpus=2_000_000_000)
        self.assertEqual(c.nano_cpus, 2_000_000_000)

    def test_nano_cpus_zero_not_rejected_at_schema_level(self) -> None:
        # The schema accepts any int; Docker itself may reject 0, but that is
        # a runtime concern.
        from cairn.shared.config.worker_models import ContainerConfig

        c = ContainerConfig(image="img", network_mode="net", completed_action="stop", nano_cpus=0)
        self.assertEqual(c.nano_cpus, 0)


# ---------------------------------------------------------------------------
# Contract validation (standalone, no YAML dependency)
# ---------------------------------------------------------------------------


class RuntimeLimitsSchemaTests(unittest.TestCase):
    def test_valid(self) -> None:
        from cairn.shared.contracts import RuntimeLimits

        r = RuntimeLimits(
            max_workers=8, max_running_projects=3, max_project_workers=4,
            interval=3, healthcheck_timeout=20, prompt_group="default",
        )
        self.assertEqual(r.max_workers, 8)

    def test_max_workers_must_be_positive(self) -> None:
        from cairn.shared.contracts import RuntimeLimits

        with self.assertRaises(Exception):
            RuntimeLimits(max_workers=0, max_running_projects=1, max_project_workers=1,
                          interval=1, healthcheck_timeout=1, prompt_group="x")

    def test_prompt_group_non_empty(self) -> None:
        from cairn.shared.contracts import RuntimeLimits

        with self.assertRaises(Exception):
            RuntimeLimits(max_workers=1, max_running_projects=1, max_project_workers=1,
                          interval=1, healthcheck_timeout=1, prompt_group="")


class ContainerLimitsSchemaTests(unittest.TestCase):
    def test_all_none_by_default(self) -> None:
        from cairn.shared.contracts import ContainerLimits

        c = ContainerLimits()
        self.assertIsNone(c.mem_limit)
        self.assertIsNone(c.pids_limit)
        self.assertIsNone(c.nano_cpus)


class ObservabilitySettingsSchemaTests(unittest.TestCase):
    def test_defaults(self) -> None:
        from cairn.shared.contracts import ObservabilitySettings

        o = ObservabilitySettings()
        self.assertTrue(o.enabled)
        self.assertTrue(o.record_prompts)
        self.assertTrue(o.record_stdout)
        self.assertTrue(o.record_stderr)
        self.assertFalse(o.record_raw_worker_stream)
        self.assertEqual(o.retention_days, 14)


class ServerLogRetentionSchemaTests(unittest.TestCase):
    def test_defaults(self) -> None:
        from cairn.shared.contracts import ServerLogRetention

        s = ServerLogRetention()
        self.assertEqual(s.log_level, "INFO")
        self.assertEqual(s.log_format, "text")
        self.assertTrue(s.retention_enabled)


# ---------------------------------------------------------------------------
# Endpoint round-trips (uses TempYamlConfig for YAML isolation)
# ---------------------------------------------------------------------------


class RuntimeLimitsEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        from helpers import TempYamlConfig
        self.yaml = TempYamlConfig()
        self.yaml.__enter__()
        from cairn.server.routers.system_config import (
            read_runtime_limits,
            write_runtime_limits,
        )
        self.read = read_runtime_limits
        self.write = write_runtime_limits

    def tearDown(self) -> None:
        self.yaml.__exit__(None, None, None)

    def test_get_returns_defaults(self) -> None:
        r = self.read()
        self.assertEqual(r.max_workers, 2)
        self.assertEqual(r.max_running_projects, 2)
        self.assertEqual(r.max_project_workers, 2)
        self.assertEqual(r.interval, 1)
        self.assertEqual(r.healthcheck_timeout, 1)
        self.assertEqual(r.prompt_group, "default")

    def test_put_round_trip(self) -> None:
        from cairn.shared.contracts import RuntimeLimits

        body = RuntimeLimits(
            max_workers=16, max_running_projects=8, max_project_workers=6,
            interval=5, healthcheck_timeout=30, prompt_group="production",
        )
        result = self.write(body)
        self.assertEqual(result.max_workers, 16)
        self.assertEqual(result.prompt_group, "production")
        # GET must reflect the update
        r = self.read()
        self.assertEqual(r.max_workers, 16)
        self.assertEqual(r.max_running_projects, 8)

    def test_put_rejects_max_project_workers_gt_max_workers(self) -> None:
        from fastapi import HTTPException

        from cairn.shared.contracts import RuntimeLimits

        body = RuntimeLimits(
            max_workers=4, max_running_projects=2, max_project_workers=8,
            interval=3, healthcheck_timeout=20, prompt_group="x",
        )
        with self.assertRaises(HTTPException) as cm:
            self.write(body)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("max_project_workers", cm.exception.detail)


class ContainerLimitsEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        from helpers import TempYamlConfig
        self.yaml = TempYamlConfig()
        self.yaml.__enter__()
        from cairn.server.routers.system_config import (
            read_container_limits,
        )
        self.read = read_container_limits

    def tearDown(self) -> None:
        self.yaml.__exit__(None, None, None)

    def test_get_defaults_none(self) -> None:
        c = self.read()
        self.assertIsNone(c.mem_limit)
        self.assertIsNone(c.pids_limit)
        self.assertIsNone(c.nano_cpus)

    def test_put_route_is_not_exported(self) -> None:
        import cairn.server.routers.system_config as router_module

        self.assertFalse(hasattr(router_module, "write_container_limits"))


class TaskTimeoutsEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        from helpers import TempYamlConfig
        self.yaml = TempYamlConfig()
        self.yaml.__enter__()
        from cairn.server.routers.system_config import (
            read_task_timeouts,
            write_task_timeouts,
        )
        self.read = read_task_timeouts
        self.write = write_task_timeouts

    def tearDown(self) -> None:
        self.yaml.__exit__(None, None, None)

    def test_get_defaults(self) -> None:
        t = self.read()
        self.assertEqual(t.bootstrap.timeout, 5)
        self.assertEqual(t.bootstrap.conclude_timeout, 5)
        self.assertEqual(t.explore.timeout, 5)
        self.assertEqual(t.explore.conclude_timeout, 5)
        self.assertEqual(t.reason.timeout, 5)
        self.assertEqual(t.reason.max_intents, 2)

    def test_put_round_trip(self) -> None:
        from cairn.shared.contracts import (
            BootstrapTaskTimeouts,
            ExploreTaskTimeouts,
            ReasonTaskTimeouts,
            TaskTimeouts,
        )

        body = TaskTimeouts(
            bootstrap=BootstrapTaskTimeouts(timeout=600, conclude_timeout=120),
            explore=ExploreTaskTimeouts(timeout=600, conclude_timeout=120),
            reason=ReasonTaskTimeouts(timeout=600, max_intents=7),
        )
        result = self.write(body)
        self.assertEqual(result.bootstrap.timeout, 600)
        self.assertEqual(result.reason.timeout, 600)
        self.assertEqual(result.reason.max_intents, 7)
        t = self.read()
        self.assertEqual(t.bootstrap.conclude_timeout, 120)
        self.assertEqual(t.explore.timeout, 600)
        self.assertEqual(t.reason.max_intents, 7)

    def test_put_without_max_intents_preserves_existing_value(self) -> None:
        from cairn.shared.contracts import (
            BootstrapTaskTimeouts,
            ExploreTaskTimeouts,
            ReasonTaskTimeouts,
            TaskTimeouts,
        )

        body = TaskTimeouts(
            bootstrap=BootstrapTaskTimeouts(timeout=600, conclude_timeout=120),
            explore=ExploreTaskTimeouts(timeout=600, conclude_timeout=120),
            reason=ReasonTaskTimeouts(timeout=600),
        )
        self.write(body)

        t = self.read()
        self.assertEqual(t.reason.timeout, 600)
        self.assertEqual(t.reason.max_intents, 2)


class ObservabilityEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        from helpers import TempYamlConfig
        # Ensure the YAML has an observability section with known defaults
        dispatch = {
            "server": {
                "base_url": "http://localhost:8000",
                "database": {"url": "postgresql+psycopg://u:p@h/db"},
                "auth": {"jwt_secret": "test-jwt-secret-do-not-use-in-prod-32bytes"},
                "paths": {"datas_root": "/tmp/cairn-test"},
                "settings": {"intent_timeout": 5, "reason_timeout": 5},
            },
            "dispatcher": {
                "health_addr": "127.0.0.1:9100",
                "reload": {"url": "http://127.0.0.1:9100/reload", "enabled": False},
                "runtime": {
                    "interval": 1, "max_workers": 2, "max_running_projects": 2,
                    "max_project_workers": 2, "healthcheck_timeout": 1, "prompt_group": "default",
                },
            },
            "tasks": {
                "bootstrap": {"timeout": 5, "conclude_timeout": 5},
                "explore": {"timeout": 5, "conclude_timeout": 5},
                "reason": {"timeout": 5, "max_intents": 2},
            },
            "observability": {
                "enabled": True,
                "record": ["prompts", "stdout"],
                "record_raw_worker_stream": False,
                "max_event_bytes": 8192,
                "max_bytes_per_execution": 5242880,
                "flush_interval_ms": 500,
                "flush_max_bytes": 4096,
                "retention_days": 30,
                "redaction_patterns": ["sk-[A-Za-z0-9]+"],
            },
            "worker_runtime": {
                "container": {
                    "image": "cairn/test:latest",
                    "network_mode": "cairn",
                    "completed_action": "stop",
                },
                "common_env": {},
            },
            "worker_pool": {"proxies": [], "workers": []},
        }
        self.yaml = TempYamlConfig(dispatch=dispatch)
        self.yaml.__enter__()
        from cairn.server.routers.system_config import (
            read_observability,
            write_observability,
        )
        self.read = read_observability
        self.write = write_observability

    def tearDown(self) -> None:
        self.yaml.__exit__(None, None, None)

    def test_get_reads_record_set(self) -> None:
        o = self.read()
        self.assertTrue(o.enabled)
        self.assertTrue(o.record_prompts)
        self.assertTrue(o.record_stdout)
        self.assertFalse(o.record_stderr)  # not in the default set
        self.assertEqual(o.max_event_bytes, 8192)
        self.assertEqual(o.retention_days, 30)
        self.assertEqual(o.redaction_patterns, ["sk-[A-Za-z0-9]+"])

    def test_put_round_trip(self) -> None:
        from cairn.shared.contracts import ObservabilitySettings

        body = ObservabilitySettings(
            enabled=False,
            record_prompts=True, record_stdout=False, record_stderr=True,
            record_raw_worker_stream=True,
            max_event_bytes=32768, max_bytes_per_execution=20971520,
            flush_interval_ms=1000, flush_max_bytes=16384,
            retention_days=7,
            redaction_patterns=["password=[^\\s]+", "token=[^\\s]+"],
        )
        result = self.write(body)
        self.assertFalse(result.enabled)
        self.assertTrue(result.record_raw_worker_stream)
        self.assertEqual(result.redaction_patterns, ["password=[^\\s]+", "token=[^\\s]+"])
        o = self.read()
        self.assertFalse(o.enabled)
        self.assertTrue(o.record_prompts)
        self.assertFalse(o.record_stdout)
        self.assertTrue(o.record_stderr)
        self.assertEqual(o.retention_days, 7)

    def test_empty_redaction_patterns(self) -> None:
        from cairn.shared.contracts import ObservabilitySettings

        body = ObservabilitySettings(redaction_patterns=[])
        result = self.write(body)
        self.assertEqual(result.redaction_patterns, [])
        o = self.read()
        self.assertEqual(o.redaction_patterns, [])


class ServerLogRetentionEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        from helpers import TempYamlConfig
        self.yaml = TempYamlConfig()
        self.yaml.__enter__()
        from cairn.server.routers.system_config import (
            read_server_log_retention,
            write_server_log_retention,
        )
        self.read = read_server_log_retention
        self.write = write_server_log_retention

    def tearDown(self) -> None:
        self.yaml.__exit__(None, None, None)

    def test_get_defaults(self) -> None:
        s = self.read()
        self.assertEqual(s.log_level, "INFO")
        self.assertEqual(s.log_format, "text")
        self.assertFalse(s.retention_enabled)

    def test_put_round_trip(self) -> None:
        from cairn.shared.contracts import ServerLogRetention

        body = ServerLogRetention(
            log_level="DEBUG", log_format="json",
            retention_enabled=True, retention_interval_seconds=3600,
        )
        result = self.write(body)
        self.assertEqual(result.log_level, "DEBUG")
        self.assertEqual(result.log_format, "json")
        self.assertTrue(result.retention_enabled)
        self.assertEqual(result.retention_interval_seconds, 3600)
        s = self.read()
        self.assertEqual(s.log_level, "DEBUG")
        self.assertEqual(s.retention_interval_seconds, 3600)

    def test_rejects_bad_log_format(self) -> None:
        from cairn.shared.contracts import ServerLogRetention

        with self.assertRaises(Exception):
            ServerLogRetention(log_format="xml")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Save-path validation: relative capability source_path must resolve against
# the REAL config dir, not the throwaway temp dir used during validation.
# ---------------------------------------------------------------------------


class ValidationPathResolutionTests(unittest.TestCase):
    """Regression: saving a section must not reject a config whose capability
    source_path is relative to the real config directory. The validator writes
    a temp copy and reloads it; relative paths previously resolved against the
    temp dir and were reported as 'does not exist'.
    """

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # A real skill directory living next to the config, referenced relatively.
        skill_dir = self.root / "capabilities" / "skills" / "demo-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# demo", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _dispatch_and_resources(self) -> tuple[dict, dict]:
        from helpers import minimal_dispatcher_config, minimal_server_config

        dispatch = {
            "server": minimal_server_config(self.root / "datas"),
            "dispatcher": minimal_dispatcher_config(),
            "tasks": {
                "bootstrap": {"timeout": 5, "conclude_timeout": 5},
                "explore": {"timeout": 5, "conclude_timeout": 5},
                "reason": {"timeout": 5, "max_intents": 2},
            },
            "observability": {},
            "worker_runtime": {
                "container": {
                    "image": "cairn/test:latest",
                    "network_mode": "cairn",
                    "completed_action": "stop",
                },
                "common_env": {},
            },
            "worker_pool": {
                "proxies": [],
                "workers": [
                    {
                        "name": "mock",
                        "type": "mock",
                        "priority": 1,
                        "max_running": 1,
                        "task_types": ["bootstrap", "explore", "reason"],
                        "env": {},
                    }
                ],
            },
        }
        resources = {
            "capabilities": {
                "mcp_servers": [],
                "skills": [
                    {
                        "id": "demo-skill",
                        "name": "Demo Skill",
                        "description": "",
                        "source_path": "./capabilities/skills/demo-skill",
                        "task_types": ["bootstrap"],
                    }
                ],
            },
            "roles": [],
        }
        return dispatch, resources

    def test_relative_capability_source_path_validates(self) -> None:
        import yaml as _yaml

        from cairn.server import runtime_config
        from cairn.server.config import files as config_files
        from helpers import split_server_dispatch_config

        dispatch, resources = self._dispatch_and_resources()
        server, dispatch = split_server_dispatch_config(dispatch)
        server_path = self.root / "server.yaml"
        dispatch_path = self.root / "config.yaml"
        resources_path = self.root / "config.resources.yaml"
        server_path.write_text(_yaml.safe_dump(server, sort_keys=False), encoding="utf-8")
        dispatch_path.write_text(_yaml.safe_dump(dispatch, sort_keys=False), encoding="utf-8")
        resources_path.write_text(_yaml.safe_dump(resources, sort_keys=False), encoding="utf-8")

        old_server = config_files.SERVER_YAML
        old_dispatch = config_files.CONFIG_YAML
        old_resources = config_files.CONFIG_RESOURCES_YAML
        old_runtime_server_path = runtime_config.DEFAULT_SERVER_CONFIG_PATH
        old_runtime_path = runtime_config.DEFAULT_DISPATCH_CONFIG_PATH
        config_files.SERVER_YAML = server_path
        config_files.CONFIG_YAML = dispatch_path
        config_files.CONFIG_RESOURCES_YAML = resources_path
        runtime_config.DEFAULT_SERVER_CONFIG_PATH = server_path
        runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = dispatch_path
        runtime_config.reset_runtime_config_cache()
        try:
            payload = dict(dispatch)
            payload["resources"] = resources
            # Must NOT raise — the relative source_path resolves against
            # the real config dir, where the skill dir actually exists.
            config_files._validate_dispatch_data(payload)
        finally:
            config_files.SERVER_YAML = old_server
            config_files.CONFIG_YAML = old_dispatch
            config_files.CONFIG_RESOURCES_YAML = old_resources
            runtime_config.DEFAULT_SERVER_CONFIG_PATH = old_runtime_server_path
            runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = old_runtime_path
            runtime_config.reset_runtime_config_cache()


if __name__ == "__main__":
    unittest.main()
