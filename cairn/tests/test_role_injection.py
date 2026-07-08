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
                    "prompts_by_phase": {
                        "reason": "This is a CTF project.\nRecover the requested flag.",
                    },
                    "prompt_sha256_by_phase": {
                        "reason": "abc123",
                    },
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

    def test_missing_phase_role_prompt_keeps_audit_summary_and_omits_instructions(self) -> None:
        from cairn.dispatcher.roles import inject_project_role

        role = inject_project_role(
            "proj_1",
            "explore",
            {
                "role": {
                    "role_id": "cypher-ctf-operator",
                    "prompts_by_phase": {"reason": "reason-only role"},
                    "prompt_sha256_by_phase": {"reason": "abc123"},
                }
            },
        )

        self.assertEqual(role.instructions, "")
        self.assertIn("missing explore role prompt", role.summary)
        self.assertEqual(role.errors, ["project:proj_1: missing explore role prompt for cypher-ctf-operator"])

    def test_role_injection_selects_current_phase_prompt(self) -> None:
        from cairn.dispatcher.roles import inject_project_role

        role_data = {
            "role": {
                "role_id": "cypher-ctf-operator",
                "role_name": "CTF Operator",
                "prompts_by_phase": {
                    "bootstrap": "bootstrap role text",
                    "explore": "explore role text",
                    "reason": "reason role text",
                },
                "prompt_sha256_by_phase": {
                    "bootstrap": "boot-sha",
                    "explore": "explore-sha",
                    "reason": "reason-sha",
                },
            }
        }

        bootstrap = inject_project_role("proj_1", "bootstrap", role_data)
        explore = inject_project_role("proj_1", "explore", role_data)
        reason = inject_project_role("proj_1", "reason", role_data)

        self.assertIn("bootstrap role text", bootstrap.instructions)
        self.assertIn("explore role text", explore.instructions)
        self.assertIn("reason role text", reason.instructions)
        self.assertEqual(bootstrap.role_prompt_sha256, "boot-sha")
        self.assertEqual(explore.role_prompt_sha256, "explore-sha")
        self.assertEqual(reason.role_prompt_sha256, "reason-sha")


if __name__ == "__main__":
    unittest.main()
