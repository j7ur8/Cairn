"""Tests for the aggregate system-config admin endpoint."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


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
        from cairn.shared.config.worker_models import ContainerConfig

        c = ContainerConfig(image="img", network_mode="net", completed_action="stop", nano_cpus=0)
        self.assertEqual(c.nano_cpus, 0)


class SystemSettingsSchemaTests(unittest.TestCase):
    def test_nested_contract_defaults_and_validation(self) -> None:
        from cairn.shared.contracts import ContainerLimits, ObservabilitySettings, RuntimeLimits, ServerLogRetention

        r = RuntimeLimits(
            max_workers=8,
            max_running_projects=3,
            max_project_workers=4,
            interval=3,
            healthcheck_timeout=20,
        )
        self.assertEqual(r.max_workers, 8)
        self.assertIsNone(ContainerLimits().nano_cpus)
        self.assertTrue(ObservabilitySettings().record_stdout)
        self.assertEqual(ServerLogRetention().log_format, "text")

        with self.assertRaises(Exception):
            RuntimeLimits(
                max_workers=0,
                max_running_projects=1,
                max_project_workers=1,
                interval=1,
                healthcheck_timeout=1,
            )
        with self.assertRaises(Exception):
            ServerLogRetention(log_format="xml")  # type: ignore[arg-type]


class SystemSettingsEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        from helpers import TempYamlConfig

        self.yaml = TempYamlConfig(dispatch=self._dispatch())
        self.yaml.__enter__()
        from cairn.server.routers.settings import get_task_timeout_defaults
        from cairn.server.routers.system_config import (
            read_container_limits,
            read_system_settings,
            write_system_settings,
        )

        self.read = read_system_settings
        self.write = write_system_settings
        self.read_container_limits = read_container_limits
        self.read_task_timeout_defaults = get_task_timeout_defaults

    def tearDown(self) -> None:
        self.yaml.__exit__(None, None, None)

    def _dispatch(self) -> dict:
        return {
            "server": {
                "base_url": "http://localhost:8000",
                "database": {"url": "postgresql+psycopg://u:p@h/db"},
                "auth": {"jwt_secret": "test-jwt-secret-do-not-use-in-prod-32bytes"},
                "paths": {"datas_root": "/tmp/cairn-test"},
                "settings": {"intent_timeout": 5, "reason_timeout": 5},
                "log": {"level": "INFO", "format": "text"},
                "retention": {"enabled": False, "interval_seconds": 21600},
            },
            "dispatcher": {
                "health_addr": "127.0.0.1:9100",
                "reload": {"url": "http://127.0.0.1:9100/reload", "enabled": False},
                "runtime": {
                    "interval": 1,
                    "max_workers": 2,
                    "max_running_projects": 2,
                    "max_project_workers": 2,
                    "healthcheck_timeout": 1,
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

    def test_get_returns_aggregate_config(self) -> None:
        result = self.read()

        self.assertEqual(result.settings.intent_timeout, 5)
        self.assertEqual(result.runtime_limits.max_workers, 2)
        self.assertEqual(result.task_timeouts.reason.max_intents, 2)
        self.assertTrue(result.observability.record_prompts)
        self.assertTrue(result.observability.record_stdout)
        self.assertFalse(result.observability.record_stderr)
        self.assertEqual(result.observability.retention_days, 30)
        self.assertEqual(result.server_log_retention.log_level, "INFO")
        self.assertFalse(result.server_log_retention.retention_enabled)

    def test_put_round_trip_writes_all_system_sections_once(self) -> None:
        body = self.read()
        body.settings.intent_timeout = 15
        body.settings.reason_timeout = 20
        body.runtime_limits.max_workers = 16
        body.runtime_limits.max_running_projects = 8
        body.runtime_limits.max_project_workers = 6
        body.runtime_limits.interval = 5
        body.runtime_limits.healthcheck_timeout = 30
        body.task_timeouts.bootstrap.timeout = 600
        body.task_timeouts.bootstrap.conclude_timeout = 120
        body.task_timeouts.explore.timeout = 650
        body.task_timeouts.explore.conclude_timeout = 130
        body.task_timeouts.reason.timeout = 700
        body.task_timeouts.reason.max_intents = 7
        body.observability.enabled = False
        body.observability.record_prompts = True
        body.observability.record_stdout = False
        body.observability.record_stderr = True
        body.observability.record_raw_worker_stream = True
        body.observability.max_event_bytes = 32768
        body.observability.max_bytes_per_execution = 20971520
        body.observability.flush_interval_ms = 1000
        body.observability.flush_max_bytes = 16384
        body.observability.retention_days = 7
        body.observability.redaction_patterns = ["password=[^\\s]+", "token=[^\\s]+"]
        body.server_log_retention.log_level = "DEBUG"
        body.server_log_retention.log_format = "json"
        body.server_log_retention.retention_enabled = True
        body.server_log_retention.retention_interval_seconds = 3600

        result = self.write(body)
        reread = self.read()

        self.assertEqual(result.settings.intent_timeout, 15)
        self.assertEqual(reread.runtime_limits.max_workers, 16)
        self.assertEqual(reread.task_timeouts.bootstrap.conclude_timeout, 120)
        self.assertEqual(reread.task_timeouts.explore.timeout, 650)
        self.assertEqual(reread.task_timeouts.reason.max_intents, 7)
        self.assertFalse(reread.observability.enabled)
        self.assertTrue(reread.observability.record_prompts)
        self.assertFalse(reread.observability.record_stdout)
        self.assertTrue(reread.observability.record_stderr)
        self.assertEqual(reread.observability.redaction_patterns, ["password=[^\\s]+", "token=[^\\s]+"])
        self.assertEqual(reread.server_log_retention.log_format, "json")
        self.assertEqual(reread.server_log_retention.retention_interval_seconds, 3600)

    def test_put_rejects_max_project_workers_gt_max_workers(self) -> None:
        from fastapi import HTTPException

        body = self.read()
        body.runtime_limits.max_workers = 4
        body.runtime_limits.max_project_workers = 8

        with self.assertRaises(HTTPException) as cm:
            self.write(body)
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("max_project_workers", cm.exception.detail)

    def test_put_without_reason_max_intents_preserves_existing_value(self) -> None:
        from cairn.shared.contracts import SystemSettingsAdmin

        raw = self.read().model_dump()
        raw["task_timeouts"]["reason"] = {"timeout": 600}
        body = SystemSettingsAdmin.model_validate(raw)

        result = self.write(body)

        self.assertEqual(result.task_timeouts.reason.timeout, 600)
        self.assertEqual(result.task_timeouts.reason.max_intents, 2)

    def test_old_admin_routes_are_not_exported(self) -> None:
        import cairn.server.routers.settings as settings_router
        import cairn.server.routers.system_config as system_router

        for name in (
            "read_runtime_limits",
            "write_runtime_limits",
            "read_task_timeouts",
            "write_task_timeouts",
            "read_observability",
            "write_observability",
            "read_server_log_retention",
            "write_server_log_retention",
        ):
            self.assertFalse(hasattr(system_router, name), name)
        self.assertFalse(hasattr(settings_router, "get_settings"))
        self.assertFalse(hasattr(settings_router, "update_settings"))

    def test_retained_non_system_endpoints_still_work(self) -> None:
        container = self.read_container_limits()
        self.assertIsNone(container.mem_limit)
        self.assertIsNone(container.pids_limit)
        self.assertIsNone(container.nano_cpus)

        defaults = self.read_task_timeout_defaults()
        self.assertEqual(defaults.reason.max_intents, 2)


class ValidationPathResolutionTests(unittest.TestCase):
    """Relative capability paths must resolve against the real config dir."""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
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
