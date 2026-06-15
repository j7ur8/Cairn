from __future__ import annotations

import json
import sys
import time
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import jwt
import yaml
from click.testing import CliRunner
from docker.errors import ImageNotFound

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


SECRET = "unit-preflight-secret-7f650e82c1714f48a2cde6f2a9f63b20"


def _service_token(secret: str = SECRET, *, role: str = "service", exp_delta: int = 86400) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "dispatcher-service",
            "iat": now,
            "nbf": now,
            "exp": now + exp_delta,
            "jti": uuid.uuid4().hex,
            "role": role,
        },
        secret,
        algorithm="HS256",
    )


def _dispatch_config(root: Path) -> dict:
    datas = root / "datas"
    attachments = datas / "attachments"
    project_files = datas / "project-files"
    attachments.mkdir(parents=True)
    project_files.mkdir(parents=True)
    return {
        "server": {
            "base_url": "http://server",
            "database": {
                "url": "postgresql+psycopg://cairn:cairn@localhost:5432/cairn",
            },
            "auth": {
                "jwt_secret": SECRET,
                "dispatcher_api_token": _service_token(),
            },
            "paths": {
                "datas_root": str(datas),
                "attachments_root": str(attachments),
                "project_files_root": str(project_files),
            },
            "settings": {
                "intent_timeout": 5,
                "reason_timeout": 5,
            },
        },
        "dispatcher": {
            "health_addr": "127.0.0.1:9100",
            "reload": {
                "url": "http://127.0.0.1:9100/reload",
                "enabled": False,
            },
            "runtime": {
                "interval": 3,
                "max_workers": 1,
                "max_running_projects": 1,
                "max_project_workers": 1,
                "healthcheck_timeout": 1,
                "prompt_group": "default",
            },
        },
        "tasks": {
            "bootstrap": {"timeout": 1, "conclude_timeout": 1},
            "reason": {"timeout": 1, "max_intents": 1},
            "explore": {"timeout": 1, "conclude_timeout": 1},
        },
        "worker_runtime": {
            "common_env": {},
            "container": {
                "image": "cairn/test:latest",
                "network_mode": "bridge",
                "completed_action": "stop",
                "bind_mounts": [
                    {
                        "name": "project-files",
                        "host_path": str(project_files / "{project_id}"),
                        "container_path": "/workspace/project",
                        "read_only": False,
                    }
                ],
            },
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


def _resources_config() -> dict:
    return {"capabilities": {"mcp_servers": [], "skills": []}, "roles": []}


class ConfigPreflightTests(unittest.TestCase):
    def _write(self, root: Path, dispatch: dict | None = None, *, resources: bool = True) -> Path:
        from helpers import split_server_dispatch_config

        server, dynamic = split_server_dispatch_config(dispatch or _dispatch_config(root))
        (root / "server.yaml").write_text(
            yaml.safe_dump(server, sort_keys=False),
            encoding="utf-8",
        )
        path = root / "config.yaml"
        path.write_text(
            yaml.safe_dump(dynamic, sort_keys=False),
            encoding="utf-8",
        )
        if resources:
            (root / "config.resources.yaml").write_text(
                yaml.safe_dump(_resources_config(), sort_keys=False),
                encoding="utf-8",
            )
        return path

    def test_valid_config_passes_with_missing_image_warning(self) -> None:
        from cairn.shared.config.preflight import check_dispatch_config

        with TemporaryDirectory() as td:
            path = self._write(Path(td))
            with mock.patch("docker.from_env") as from_env:
                from_env.return_value.images.get.side_effect = ImageNotFound("missing")
                result = check_dispatch_config(path)

        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(result.errors, [])
        self.assertTrue(any("worker image" in warning for warning in result.warnings))

    def test_strict_missing_image_fails(self) -> None:
        from cairn.shared.config.preflight import check_dispatch_config

        with TemporaryDirectory() as td:
            path = self._write(Path(td))
            with mock.patch("docker.from_env") as from_env:
                from_env.return_value.images.get.side_effect = ImageNotFound("missing")
                result = check_dispatch_config(path, strict=True)

        self.assertFalse(result.ok)
        self.assertTrue(any("worker image" in error for error in result.errors))

    def test_placeholder_jwt_secret_fails(self) -> None:
        from cairn.shared.config.preflight import check_dispatch_config

        with TemporaryDirectory() as td:
            root = Path(td)
            dispatch = _dispatch_config(root)
            dispatch["server"]["auth"]["jwt_secret"] = "change-me-generate-secret"
            dispatch["server"]["auth"]["dispatcher_api_token"] = "change-me-token"
            result = check_dispatch_config(self._write(root, dispatch))

        self.assertFalse(result.ok)
        self.assertTrue(any("jwt_secret" in error for error in result.errors))
        self.assertTrue(any("dispatcher_api_token" in error for error in result.errors))

    def test_dispatcher_token_signed_by_different_secret_fails(self) -> None:
        from cairn.shared.config.preflight import check_dispatch_config

        with TemporaryDirectory() as td:
            root = Path(td)
            dispatch = _dispatch_config(root)
            dispatch["server"]["auth"]["dispatcher_api_token"] = _service_token("different-secret-32-characters-long")
            result = check_dispatch_config(self._write(root, dispatch))

        self.assertFalse(result.ok)
        self.assertTrue(any("not valid for jwt_secret" in error for error in result.errors))

    def test_dispatcher_token_requires_service_role(self) -> None:
        from cairn.shared.config.preflight import check_dispatch_config

        with TemporaryDirectory() as td:
            root = Path(td)
            dispatch = _dispatch_config(root)
            dispatch["server"]["auth"]["dispatcher_api_token"] = _service_token(role="user")
            result = check_dispatch_config(self._write(root, dispatch))

        self.assertFalse(result.ok)
        self.assertTrue(any("role=service" in error for error in result.errors))

    def test_missing_resources_file_fails(self) -> None:
        from cairn.shared.config.preflight import check_dispatch_config

        with TemporaryDirectory() as td:
            path = self._write(Path(td), resources=False)
            result = check_dispatch_config(path)

        self.assertFalse(result.ok)
        self.assertTrue(any("config.resources.yaml" in error for error in result.errors))

    def test_cli_config_check_outputs_json_and_sets_exit_code(self) -> None:
        from cairn.cli import main

        with TemporaryDirectory() as td:
            root = Path(td)
            good_root = root / "good"
            bad_root = root / "bad"
            good_root.mkdir()
            bad_root.mkdir()
            path = self._write(good_root)
            dispatch = _dispatch_config(bad_root)
            dispatch["server"]["auth"]["dispatcher_api_token"] = "not-a-jwt"
            bad_path = self._write(bad_root, dispatch)

            with mock.patch("docker.from_env") as from_env:
                from_env.return_value.images.get.return_value = object()
                ok = CliRunner().invoke(main, ["config", "check", "--config", str(path)])
                failed = CliRunner().invoke(main, ["config", "check", "--config", str(bad_path)])

        self.assertEqual(ok.exit_code, 0, ok.output)
        self.assertTrue(json.loads(ok.output)["ok"])
        self.assertEqual(failed.exit_code, 1, failed.output)
        self.assertFalse(json.loads(failed.output)["ok"])


if __name__ == "__main__":
    unittest.main()
