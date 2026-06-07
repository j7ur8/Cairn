from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class TaskTypeRegistryTests(unittest.TestCase):
    def test_builtin_task_types_registered(self) -> None:
        from cairn.server.task_types import TASK_TYPE_REGISTRY
        self.assertIn("bootstrap", TASK_TYPE_REGISTRY.names())
        self.assertIn("explore", TASK_TYPE_REGISTRY.names())
        self.assertIn("reason", TASK_TYPE_REGISTRY.names())
        self.assertIn("legacy", TASK_TYPE_REGISTRY.names())

    def test_register_new_task_type(self) -> None:
        from cairn.server.task_types import TASK_TYPE_REGISTRY, register_task_type
        register_task_type("custom_test", description="custom")
        self.assertTrue(TASK_TYPE_REGISTRY.is_valid("custom_test"))
        self.assertEqual(TASK_TYPE_REGISTRY.get("custom_test").description, "custom")

    def test_project_snapshot_rejects_unknown_task_type(self) -> None:
        from pydantic import ValidationError
        from cairn.server.models import ProjectAiProfileSnapshot
        with self.assertRaises(ValidationError):
            ProjectAiProfileSnapshot(
                profile_id="ai1",
                task_type="not_registered",
                role="primary",
                position=0,
                snapshot_name="n",
                snapshot_worker_type="codex",
                snapshot_model="m",
                snapshot_api_key_env="OPENAI_API_KEY",
            )

    def test_observability_record_set_computed_booleans(self) -> None:
        from cairn.server.observability.models import ObservabilitySettings
        s = ObservabilitySettings(record={"stdout"})
        self.assertFalse(s.record_prompts)
        self.assertTrue(s.record_stdout)
        self.assertFalse(s.record_stderr)


if __name__ == "__main__":
    unittest.main()
