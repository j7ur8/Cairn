from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class RoleInjectionTests(unittest.TestCase):
    def test_instructions_are_project_type_only_without_wrapper_metadata(self) -> None:
        from cairn.dispatcher.roles import inject_project_role

        role = inject_project_role(
            "proj_1",
            "reason",
            {
                "role": {
                    "role_id": "cypher-ctf-operator",
                    "role_name": "CTF Operator",
                    "role_prompt": "This is a CTF project.\nRecover the requested flag.",
                    "role_prompt_sha256": "abc123",
                }
            },
        )

        self.assertTrue(role.instructions.startswith("## Project Type\n"))
        self.assertIn("This is a CTF project.", role.instructions)
        self.assertNotIn("selected a primary role", role.instructions)
        self.assertNotIn("Role prompt sha256", role.instructions)
        self.assertNotIn("```", role.instructions)
        self.assertEqual(role.role_id, "cypher-ctf-operator")
        self.assertEqual(role.role_prompt_sha256, "abc123")
        self.assertIn('"role_id": "cypher-ctf-operator"', role.summary)
        self.assertIn('"role_prompt_sha256": "abc123"', role.summary)

    def test_invalid_role_snapshot_keeps_audit_summary_and_omits_instructions(self) -> None:
        from cairn.dispatcher.roles import inject_project_role

        role = inject_project_role(
            "proj_1",
            "explore",
            {"role": {"role_id": "cypher-ctf-operator"}},
        )

        self.assertEqual(role.instructions, "")
        self.assertIn("invalid role snapshot", role.summary)
        self.assertEqual(role.errors, ["project:proj_1: invalid role snapshot"])


if __name__ == "__main__":
    unittest.main()
