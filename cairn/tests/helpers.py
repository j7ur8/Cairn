from __future__ import annotations

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

_TEST_DISPATCH_PATH = Path(__file__).resolve().parents[2] / "dispatch.test.yaml"
runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = _TEST_DISPATCH_PATH
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

    if not Path(runtime_config.DEFAULT_DISPATCH_CONFIG_PATH).exists():
        runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = _TEST_DISPATCH_PATH
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


class TempYamlConfig:
    def __init__(self, dispatch: dict[str, Any] | None = None, resources: dict[str, Any] | None = None):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.dispatch_path = self.root / "dispatch.yaml"
        self.resources_path = self.root / "dispatch.resources.yaml"
        self.capabilities_path = self.resources_path
        self.dispatch = dispatch or {
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
        self.resources = resources or {"capabilities": {"mcp_servers": [], "skills": []}, "roles": []}
        from cairn.server.config import files as config_files
        self._old_dispatch_path = runtime_config.DEFAULT_DISPATCH_CONFIG_PATH
        self._old_yaml_dispatch_path = config_files.DISPATCH_YAML
        self._old_yaml_resources_path = config_files.RESOURCES_YAML

    def __enter__(self) -> TempYamlConfig:
        from cairn.server.config import files as config_files

        self.dispatch_path.write_text(yaml.safe_dump(self.dispatch, sort_keys=False), encoding="utf-8")
        self.resources_path.write_text(yaml.safe_dump(self.resources, sort_keys=False), encoding="utf-8")
        runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = self.dispatch_path
        runtime_config.reset_runtime_config_cache()
        config_files.DISPATCH_YAML = self.dispatch_path
        config_files.RESOURCES_YAML = self.resources_path
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        from cairn.server.config import files as config_files
        runtime_config.DEFAULT_DISPATCH_CONFIG_PATH = self._old_dispatch_path
        runtime_config.reset_runtime_config_cache()
        config_files.DISPATCH_YAML = self._old_yaml_dispatch_path
        config_files.RESOURCES_YAML = self._old_yaml_resources_path
        self._tmp.cleanup()
