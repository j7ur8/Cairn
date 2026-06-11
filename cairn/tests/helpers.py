from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml
from sqlalchemy import create_engine, text

from cairn.server import runtime_config


_TEST_DISPATCH_PATH = Path(__file__).resolve().parents[2] / "dispatch.test.yaml"
runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = _TEST_DISPATCH_PATH
runtime_config.reset_runtime_config_cache()


def minimal_system_config(root: Path | None = None) -> dict[str, Any]:
    base = root or Path("/tmp/cairn-test")
    return {
        "database": {
            "url": "postgresql+psycopg://cairn:cairn@localhost:5432/cairn",
            "pool_size": 5,
            "max_overflow": 10,
            "pool_timeout": 30,
        },
        "auth": {
            "jwt_secret": "test-jwt-secret-do-not-use-in-prod-32bytes",
            "dispatcher_api_token": "test-dispatcher-token",
        },
        "initial_admin": {"email": "", "password": ""},
        "paths": {
            "datas_root": str(base),
            "attachments_root": str(base / "attachments"),
            "project_files_root": str(base / "project-files"),
            "worker_attachments_root": "/mnt/attachments",
        },
        "dispatcher": {
            "reload_url": "http://127.0.0.1:9100/reload",
            "reload_enabled": False,
            "health_addr": "127.0.0.1:9100",
        },
        "server": {
            "log_level": "INFO",
            "log_format": "text",
            "retention_loop_enabled": False,
            "retention_interval_seconds": 21600,
        },
    }


def reset_postgres_db():
    from cairn.server import db
    from cairn.server.runtime_config import system_config

    database_url = system_config().database.url
    lock_engine = create_engine(database_url, pool_pre_ping=True, future=True)
    try:
        with lock_engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_lock(620533464)"))
            try:
                db.reset_for_tests()
                db.configure(database_url, run_migrations=False)
                db.drop_all_for_tests()
                db.upgrade_head()
                db.seed_defaults()
            finally:
                db.reset_for_tests()
                conn.execute(text("SELECT pg_advisory_unlock(620533464)"))
    finally:
        lock_engine.dispose()
    db.configure(database_url, run_migrations=False)
    return db


class TempYamlConfig:
    def __init__(self, dispatch: dict[str, Any] | None = None, capabilities: dict[str, Any] | None = None):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.dispatch_path = self.root / "dispatch.yaml"
        self.capabilities_path = self.root / "dispatch.capabilities.yaml"
        self.dispatch = dispatch or {
            "system": minimal_system_config(self.root / "datas"),
            "server": "http://localhost:8000",
            "common_env": {},
            "runtime": {
                "interval": 1,
                "max_workers": 2,
                "max_running_projects": 2,
                "max_project_workers": 2,
                "healthcheck_timeout": 1,
                "prompt_group": "default",
            },
            "tasks": {
                "bootstrap": {"timeout": 5, "conclude_timeout": 5},
                "explore": {"timeout": 5, "conclude_timeout": 5},
                "reason": {"timeout": 5, "max_intents": 2},
            },
            "container": {
                "image": "cairn/test:latest",
                "network_mode": "cairn",
                "completed_action": "stop",
            },
            "workers": [],
        }
        self.capabilities = capabilities or {"capabilities": {"mcp_servers": [], "skills": []}, "roles": []}
        from cairn.server.config import files as config_files
        self._old_dispatch_path = runtime_config.DEFAULT_DISPATCH_CONFIG_PATH
        self._old_yaml_dispatch_path = config_files.DISPATCH_YAML
        self._old_yaml_capabilities_path = config_files.CAPABILITIES_YAML

    def __enter__(self) -> "TempYamlConfig":
        from cairn.server.config import files as config_files

        self.dispatch_path.write_text(yaml.safe_dump(self.dispatch, sort_keys=False), encoding="utf-8")
        self.capabilities_path.write_text(yaml.safe_dump(self.capabilities, sort_keys=False), encoding="utf-8")
        runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = self.dispatch_path
        runtime_config.reset_runtime_config_cache()
        config_files.DISPATCH_YAML = self.dispatch_path
        config_files.CAPABILITIES_YAML = self.capabilities_path
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        from cairn.server.config import files as config_files
        runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = self._old_dispatch_path
        runtime_config.reset_runtime_config_cache()
        config_files.DISPATCH_YAML = self._old_yaml_dispatch_path
        config_files.CAPABILITIES_YAML = self._old_yaml_capabilities_path
        self._tmp.cleanup()
