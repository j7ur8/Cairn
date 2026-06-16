from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


def _write_prompt_group(root: Path, group: str, overrides: dict[str, str] | None = None) -> None:
    from cairn.server.execution_config.prompt_snapshot import PROMPT_SNAPSHOT_NAMES
    from cairn.shared.config.constants import DEFAULT_PROMPT_REQUIRED_TOKENS

    overrides = overrides or {}
    group_dir = root / group
    group_dir.mkdir(parents=True, exist_ok=True)
    for name in PROMPT_SNAPSHOT_NAMES:
        tokens = " ".join(DEFAULT_PROMPT_REQUIRED_TOKENS.get(name, ()))
        content = overrides.get(name, f"{name}\n{tokens}\n")
        (group_dir / name).write_text(content, encoding="utf-8")


class PromptGroupAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _write_prompt_group(self.root, "default")
        _write_prompt_group(self.root, "custom")

        import cairn.server.routers.prompt_groups as prompt_groups

        self.router = prompt_groups
        self.root_patch = mock.patch.object(prompt_groups, "_prompts_root", return_value=self.root.resolve())
        self.root_patch.start()
        self.files_patch = mock.patch("cairn.server.execution_config.prompt_snapshot.resources.files")
        files = self.files_patch.start()
        files.return_value.joinpath.side_effect = lambda group: self.root / group

    def tearDown(self) -> None:
        self.files_patch.stop()
        self.root_patch.stop()
        self.tmp.cleanup()

    def test_list_prompt_groups(self) -> None:
        result = self.router.list_prompt_groups()

        self.assertEqual(result["groups"], ["custom", "default"])

    def test_read_prompt_group_returns_templates_and_hashes(self) -> None:
        result = self.router.read_prompt_group("default")

        self.assertEqual(result["prompt_group"], "default")
        self.assertEqual(
            set(result["prompts"]),
            {"bootstrap.md", "bootstrap_conclude.md", "explore.md", "explore_conclude.md", "reason.md"},
        )
        self.assertRegex(result["prompt_sha256"]["reason.md"], r"^[0-9a-f]{64}$")
        self.assertRegex(result["prompts_sha256"], r"^[0-9a-f]{64}$")

    def test_update_prompt_template_writes_file_and_updates_hash(self) -> None:
        from cairn.shared.config.constants import DEFAULT_PROMPT_REQUIRED_TOKENS

        before = self.router.read_prompt_group("default")
        content = "updated reason\n" + " ".join(DEFAULT_PROMPT_REQUIRED_TOKENS["reason.md"]) + "\n"
        body = self.router.PromptGroupTemplateUpdate(content=content)
        after = self.router.update_prompt_template("default", "reason.md", body)

        self.assertEqual((self.root / "default" / "reason.md").read_text(encoding="utf-8"), content)
        self.assertEqual(after["prompts"]["reason.md"], content)
        self.assertNotEqual(before["prompt_sha256"]["reason.md"], after["prompt_sha256"]["reason.md"])
        self.assertNotEqual(before["prompts_sha256"], after["prompts_sha256"])

    def test_update_missing_required_placeholder_fails_without_writing(self) -> None:
        from fastapi import HTTPException

        original = (self.root / "default" / "reason.md").read_text(encoding="utf-8")
        body = self.router.PromptGroupTemplateUpdate(content="{graph_yaml}\n")

        with self.assertRaises(HTTPException) as cm:
            self.router.update_prompt_template("default", "reason.md", body)

        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("missing placeholders", cm.exception.detail)
        self.assertEqual((self.root / "default" / "reason.md").read_text(encoding="utf-8"), original)

    def test_invalid_group_name_and_template_name_are_rejected(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as group_cm:
            self.router.read_prompt_group("../default")
        with self.assertRaises(HTTPException) as name_cm:
            self.router.update_prompt_template(
                "default",
                "../reason.md",
                self.router.PromptGroupTemplateUpdate(content="x"),
            )

        self.assertEqual(group_cm.exception.status_code, 404)
        self.assertEqual(name_cm.exception.status_code, 400)


class PromptSettingsFrontendTests(unittest.TestCase):
    def test_settings_contains_prompt_editor_controls(self) -> None:
        view = (_REPO / "cairn" / "src" / "cairn" / "server" / "partials" / "view_settings.html").read_text(
            encoding="utf-8"
        )
        ui = (_REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "parts.ui.js").read_text(
            encoding="utf-8"
        )
        capabilities = (
            _REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "parts.capabilities.js"
        ).read_text(encoding="utf-8")

        self.assertIn("section: 'prompts'", ui)
        self.assertIn("settingsSection === 'prompts'", view)
        self.assertIn('data-testid="prompts-group"', view)
        self.assertIn('data-testid="prompts-editor"', view)
        self.assertIn('data-testid="prompts-save"', view)
        self.assertIn("/prompt-groups", capabilities)

    def test_settings_capabilities_is_two_column_and_type_specific(self) -> None:
        view = (_REPO / "cairn" / "src" / "cairn" / "server" / "partials" / "view_settings.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("data-testid=\"settings-capability-add-mcp\"", view)
        self.assertIn("data-testid=\"settings-capability-add-skill\"", view)
        self.assertIn("Import MCP JSON", view)
        self.assertIn("MCP Servers", view)
        self.assertIn("Skills", view)
        self.assertNotIn("capabilityAdminPanel", view)
        self.assertNotIn("capabilityTaskTypes()", view)


if __name__ == "__main__":
    unittest.main()
