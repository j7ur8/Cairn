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


class YamlConfigWriteTests(unittest.TestCase):
    def test_atomic_write_falls_back_for_single_file_bind_mount_busy(self) -> None:
        from cairn.server.config.files import _atomic_write_yaml

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "dispatch.capabilities.yaml"
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
            target.write_text("workers: []\n", encoding="utf-8")

            with patch.object(Path, "replace", side_effect=OSError(errno.EACCES, "denied")):
                with self.assertRaises(OSError):
                    _atomic_write_yaml(target, {"workers": []})


if __name__ == "__main__":
    unittest.main()
