from __future__ import annotations

import os
import time
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import jwt
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from cairn.server import runtime_config
from cairn.shared.contracts import TaskTimeouts

_TEST_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.test.yaml"
_TEST_SERVER_PATH = Path(__file__).resolve().parents[2] / "server.test.yaml"
runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = _TEST_CONFIG_PATH
runtime_config.DEFAULT_SERVER_CONFIG_PATH = _TEST_SERVER_PATH
runtime_config.reset_runtime_config_cache()


def minimal_server_config(root: Path | None = None) -> dict[str, Any]:
    base = root or Path("/tmp/cairn-test")
    jwt_secret = "test-jwt-secret-do-not-use-in-prod-32bytes"
    return {
        "base_url": "http://localhost:8000",
        "database": {
            "url": "postgresql+psycopg://cairn:cairn@localhost:5432/cairn",
            "pool_size": 5,
            "max_overflow": 10,
            "pool_timeout": 30,
        },
        "auth": {
            "jwt_secret": jwt_secret,
            "dispatcher_api_token": _service_token(jwt_secret),
        },
        "initial_admin": {"email": "", "password": ""},
        "paths": {
            "datas_root": str(base),
            "attachments_root": str(base / "attachments"),
            "project_files_root": str(base / "project-files"),
            "worker_attachments_root": "/home/kali/workspace/attachments",
        },
        "log": {
            "level": "INFO",
            "format": "text",
        },
        "retention": {
            "enabled": False,
            "interval_seconds": 21600,
        },
        "settings": {
            "intent_timeout": 5,
            "reason_timeout": 5,
        },
    }


def _service_token(jwt_secret: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "dispatcher-service",
            "iat": now,
            "nbf": now,
            "exp": now + 60 * 60 * 24 * 365,
            "jti": uuid.uuid4().hex,
            "role": "service",
        },
        jwt_secret,
        algorithm="HS256",
    )


def minimal_system_config(root: Path | None = None) -> dict[str, Any]:
    server = minimal_server_config(root)
    return {
        "database": server["database"],
        "auth": server["auth"],
        "initial_admin": server["initial_admin"],
        "paths": server["paths"],
        "dispatcher": {
            "reload_url": "http://127.0.0.1:9100/reload",
            "reload_enabled": False,
            "health_addr": "127.0.0.1:9100",
        },
        "server": {
            "log_level": server["log"]["level"],
            "log_format": server["log"]["format"],
            "retention_loop_enabled": server["retention"]["enabled"],
            "retention_interval_seconds": server["retention"]["interval_seconds"],
        },
    }


def minimal_dispatcher_config() -> dict[str, Any]:
    return {
        "health_addr": "127.0.0.1:9100",
        "reload": {
            "url": "http://127.0.0.1:9100/reload",
            "enabled": False,
        },
        "runtime": {
            "interval": 1,
            "max_workers": 2,
            "max_running_projects": 2,
            "max_project_workers": 2,
            "healthcheck_timeout": 1,
            "prompt_group": "default",
        },
    }


def test_task_timeouts(
    *,
    bootstrap_timeout: int = 5,
    bootstrap_conclude_timeout: int = 5,
    explore_timeout: int = 5,
    explore_conclude_timeout: int = 5,
    reason_timeout: int = 5,
) -> TaskTimeouts:
    return TaskTimeouts.model_validate(
        {
            "bootstrap": {"timeout": bootstrap_timeout, "conclude_timeout": bootstrap_conclude_timeout},
            "explore": {"timeout": explore_timeout, "conclude_timeout": explore_conclude_timeout},
            "reason": {"timeout": reason_timeout},
        }
    )


test_task_timeouts.__test__ = False


def reset_postgres_db():
    from cairn.server import db
    from cairn.server.runtime_config import system_config

    # Safety gate: this helper DROPS the entire schema. It must never run
    # against a database that was not explicitly designated disposable. The
    # caller (CI, or a developer pointing at a throwaway DB) must opt in via
    # CAIRN_ALLOW_DB_RESET=1. Without it we skip rather than risk wiping a
    # live database that happens to be the configured target.
    if os.environ.get("CAIRN_ALLOW_DB_RESET") != "1":
        raise unittest.SkipTest(
            "DB integration tests skipped: set CAIRN_ALLOW_DB_RESET=1 and point "
            "config.test.yaml at a disposable database (these tests DROP the schema)."
        )

    if not Path(runtime_config.DEFAULT_DISPATCH_CONFIG_PATH).exists():
        runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = _TEST_CONFIG_PATH
        runtime_config.reset_runtime_config_cache()

    database_url = system_config().database.url
    lock_engine = create_engine(
        database_url,
        pool_pre_ping=True,
        future=True,
        connect_args={"connect_timeout": 1},
    )
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
    except SQLAlchemyError as exc:
        raise unittest.SkipTest(f"PostgreSQL is not available for DB integration tests: {exc}") from exc
    finally:
        lock_engine.dispose()
    db.configure(database_url, run_migrations=False)
    return db


def split_server_dispatch_config(dispatch: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    fixed_server_keys = ("base_url", "database", "auth", "initial_admin", "paths")
    dynamic_server_keys = ("log", "retention", "settings")
    fixed_dispatcher_keys = ("health_addr", "reload")
    dynamic_dispatcher_keys = ("runtime",)
    source_server = dispatch.get("server") if isinstance(dispatch.get("server"), dict) else {}
    source_dispatcher = dispatch.get("dispatcher") if isinstance(dispatch.get("dispatcher"), dict) else {}
    server = {
        "server": {key: source_server[key] for key in fixed_server_keys if key in source_server},
        "dispatcher": {key: source_dispatcher[key] for key in fixed_dispatcher_keys if key in source_dispatcher},
    }
    if "worker_runtime" in dispatch:
        server["worker_runtime"] = dispatch["worker_runtime"]
    dynamic = dict(dispatch)
    dynamic.pop("worker_runtime", None)
    dynamic["server"] = {key: source_server[key] for key in dynamic_server_keys if key in source_server}
    dynamic["dispatcher"] = {key: source_dispatcher[key] for key in dynamic_dispatcher_keys if key in source_dispatcher}
    return server, dynamic


class TempYamlConfig:
    def __init__(
        self,
        dispatch: dict[str, Any] | None = None,
        resources: dict[str, Any] | None = None,
        server: dict[str, Any] | None = None,
    ):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.server_path = self.root / "server.yaml"
        self.dispatch_path = self.root / "config.yaml"
        self.resources_path = self.root / "config.resources.yaml"
        self.capabilities_path = self.resources_path
        combined = dispatch or {
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
                "workers": [],
            },
        }
        self.server = server
        self.dispatch = combined
        self.written_server: dict[str, Any] | None = None
        self.written_dispatch: dict[str, Any] | None = None
        self.resources = resources or {"capabilities": {"mcp_servers": [], "skills": []}, "roles": []}
        from cairn.server.config import files as config_files
        self._old_dispatch_path = runtime_config.DEFAULT_DISPATCH_CONFIG_PATH
        self._old_server_path = runtime_config.DEFAULT_SERVER_CONFIG_PATH
        self._old_yaml_server_path = config_files.SERVER_YAML
        self._old_yaml_dispatch_path = config_files.CONFIG_YAML
        self._old_yaml_resources_path = config_files.CONFIG_RESOURCES_YAML

    def __enter__(self) -> TempYamlConfig:
        from cairn.server.config import files as config_files

        split_server, split_dispatch = split_server_dispatch_config(self.dispatch)
        self.written_server = self.server or split_server
        self.written_dispatch = split_dispatch
        self.server_path.write_text(yaml.safe_dump(self.written_server, sort_keys=False), encoding="utf-8")
        self.dispatch_path.write_text(yaml.safe_dump(self.written_dispatch, sort_keys=False), encoding="utf-8")
        self.resources_path.write_text(yaml.safe_dump(self.resources, sort_keys=False), encoding="utf-8")
        runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = self.dispatch_path
        runtime_config.DEFAULT_SERVER_CONFIG_PATH = self.server_path
        runtime_config.reset_runtime_config_cache()
        config_files.SERVER_YAML = self.server_path
        config_files.CONFIG_YAML = self.dispatch_path
        config_files.CONFIG_RESOURCES_YAML = self.resources_path
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        from cairn.server.config import files as config_files
        runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = self._old_dispatch_path
        runtime_config.DEFAULT_SERVER_CONFIG_PATH = self._old_server_path
        runtime_config.reset_runtime_config_cache()
        config_files.SERVER_YAML = self._old_yaml_server_path
        config_files.CONFIG_YAML = self._old_yaml_dispatch_path
        config_files.CONFIG_RESOURCES_YAML = self._old_yaml_resources_path
        self._tmp.cleanup()
