from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class TaskTypesRouterTests(unittest.TestCase):
    """DB-free: the task-types listing is sourced from the in-process registry."""

    def test_list_task_types_mirrors_registry(self) -> None:
        from cairn.server.routers import task_types
        from cairn.shared.task_types import TASK_TYPE_REGISTRY

        result = task_types.list_task_types()
        names = {entry["name"] for entry in result}
        registry_names = {spec.name for spec in TASK_TYPE_REGISTRY.specs()}
        self.assertEqual(names, registry_names)

    def test_list_task_types_entries_have_schema_fields(self) -> None:
        from cairn.server.routers import task_types

        result = task_types.list_task_types()
        self.assertTrue(result, "registry should expose at least one task type")
        for entry in result:
            self.assertIn("name", entry)
            self.assertIn("description", entry)
            self.assertIn("json_schema", entry)


if __name__ == "__main__":
    unittest.main()
