from __future__ import annotations

import errno
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

from helpers import TempYamlConfig


class YamlConfigWriteTests(unittest.TestCase):
    def test_atomic_write_falls_back_for_single_file_bind_mount_busy(self) -> None:
        from cairn.server.config.files import _atomic_write_yaml

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "dispatch.resources.yaml"
            target.write_text("roles: []\n", encoding="utf-8")

            with patch.object(Path, "replace", side_effect=OSError(errno.EBUSY, "busy")):
                _atomic_write_yaml(target, {"roles": [{"id": "role1", "name": "Role"}]})

            self.assertEqual(
                yaml.safe_load(target.read_text(encoding="utf-8")),
                {"roles": [{"id": "role1", "name": "Role"}]},
            )

    def test_atomic_write_reraises_non_busy_replace_errors(self) -> None:
        from cairn.server.config.files import _atomic_write_yaml

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "dispatch.yaml"
            target.write_text("worker_pool:\n  workers: []\n", encoding="utf-8")

            with patch.object(Path, "replace", side_effect=OSError(errno.EACCES, "denied")):
                with self.assertRaises(OSError):
                    _atomic_write_yaml(target, {"worker_pool": {"workers": []}})


class SettingsConfigTests(unittest.TestCase):
    def test_settings_do_not_fallback_to_or_write_tasks(self) -> None:
        from cairn.server.config.settings import get_yaml_settings, get_yaml_task_timeouts, update_yaml_settings
        from cairn.server.models_pkg.common import Settings

        dispatch = TempYamlConfig().dispatch
        dispatch["server"]["settings"] = {"intent_timeout": 90, "reason_timeout": 300}
        dispatch["tasks"]["explore"]["conclude_timeout"] = 17
        dispatch["tasks"]["reason"]["timeout"] = 23
        with TempYamlConfig(dispatch=dispatch) as cfg:
            settings = get_yaml_settings()
            self.assertEqual(settings.intent_timeout, 90)
            self.assertEqual(settings.reason_timeout, 300)

            update_yaml_settings(Settings(intent_timeout=111, reason_timeout=222))
            data = yaml.safe_load(cfg.dispatch_path.read_text(encoding="utf-8"))
            self.assertEqual(data["server"]["settings"], {"intent_timeout": 111, "reason_timeout": 222})
            self.assertEqual(data["tasks"]["explore"]["conclude_timeout"], 17)
            self.assertEqual(data["tasks"]["reason"]["timeout"], 23)

            defaults = get_yaml_task_timeouts()
            self.assertEqual(defaults.explore.conclude_timeout, 17)
            self.assertEqual(defaults.reason.timeout, 23)

    def test_settings_require_server_settings_fields(self) -> None:
        from fastapi import HTTPException

        from cairn.server.config.settings import get_yaml_settings

        dispatch = TempYamlConfig().dispatch
        dispatch["server"].pop("settings", None)
        with TempYamlConfig(dispatch=dispatch):
            with self.assertRaises(HTTPException) as ctx:
                get_yaml_settings()
            self.assertEqual(ctx.exception.status_code, 500)


if __name__ == "__main__":
    unittest.main()
