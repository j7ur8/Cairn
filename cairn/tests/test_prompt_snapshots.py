from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class PromptSnapshotTests(unittest.TestCase):
    def test_default_templates_keep_role_in_task_and_exclude_it_from_conclude(self) -> None:
        default_dir = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts" / "default"

        bootstrap = (default_dir / "bootstrap.md").read_text(encoding="utf-8")
        explore = (default_dir / "explore.md").read_text(encoding="utf-8")
        reason = (default_dir / "reason.md").read_text(encoding="utf-8")
        bootstrap_conclude = (default_dir / "bootstrap_conclude.md").read_text(encoding="utf-8")
        explore_conclude = (default_dir / "explore_conclude.md").read_text(encoding="utf-8")

        self.assertIn("# Task\n", bootstrap)
        self.assertIn("# Task\n", explore)
        self.assertIn("# Task\n", reason)
        self.assertIn("{role_instructions}", bootstrap.split("# Output Requirements", 1)[0])
        self.assertIn("{role_instructions}", explore.split("# Output Requirements", 1)[0])
        self.assertIn("{role_instructions}", reason.split("# Output Requirements", 1)[0])
        self.assertNotIn("{role_instructions}", bootstrap_conclude)
        self.assertNotIn("{role_instructions}", explore_conclude)

    def test_default_explore_uses_plain_text_sentinel_output(self) -> None:
        default_dir = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts" / "default"
        explore = (default_dir / "explore.md").read_text(encoding="utf-8")

        output_requirements = explore.split("# Output Requirements", 1)[1].split("# Rules", 1)[0]
        self.assertIn("32173462130721312360912", output_requirements)
        self.assertIn("plain text", output_requirements)
        self.assertIn("Do not output JSON", output_requirements)
        self.assertNotIn("Return only one raw JSON object", output_requirements)

    def test_default_reason_uses_marker_gated_output(self) -> None:
        default_dir = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts" / "default"
        reason = (default_dir / "reason.md").read_text(encoding="utf-8")

        output_requirements = reason.split("# Output Requirements", 1)[1].split("## Rules", 1)[0]
        self.assertIn("32173462130721312360912", output_requirements)
        self.assertIn("84913462130721312360912", output_requirements)
        self.assertIn("00003462130721312360912", output_requirements)
        self.assertIn('{"accepted": true, "data": {"complete"', output_requirements)
        self.assertIn('{"accepted": true, "data": {"intents"', output_requirements)
        self.assertIn('{"accepted": true, "data": {}}', output_requirements)
        self.assertNotIn("Return only one raw JSON object", output_requirements)

    def test_load_prompt_snapshot_hash_changes_with_content(self) -> None:
        from cairn.server.execution_config.prompt_snapshot import load_prompt_snapshot

        first = load_prompt_snapshot("mock")
        original = first["prompts"]["reason.md"]
        prompts = dict(first["prompts"])
        prompts["reason.md"] = f"{original}\nextra"
        with tempfile.TemporaryDirectory() as tmp:
            group_dir = Path(tmp) / "mock"
            group_dir.mkdir()
            for name, content in prompts.items():
                (group_dir / name).write_text(content, encoding="utf-8")
            with mock.patch("cairn.server.execution_config.prompt_snapshot.resources.files") as files:
                files.return_value.joinpath.side_effect = lambda group: Path(tmp) / group
                changed = load_prompt_snapshot("mock")

        self.assertEqual(
            set(first["prompts"]),
            {"bootstrap.md", "bootstrap_conclude.md", "explore.md", "explore_conclude.md", "reason.md", "FILE_OUTPUTS.md"},
        )
        self.assertEqual(first["prompt_group"], "mock")
        self.assertNotEqual(first["prompts_sha256"], changed["prompts_sha256"])

    def test_load_prompt_from_execution_config_uses_snapshot(self) -> None:
        from cairn.dispatcher.prompting import load_prompt_from_execution_config

        reporter = mock.Mock()
        prompt = load_prompt_from_execution_config(
            {"prompt_snapshot": {"prompts": {"reason.md": "SNAPSHOT"}}},
            "reason.md",
            "mock",
            reporter,
        )

        self.assertEqual(prompt, "SNAPSHOT")
        reporter.emit_error.assert_not_called()

    def test_load_prompt_from_execution_config_falls_back_and_warns(self) -> None:
        from cairn.dispatcher.prompting import load_prompt_from_execution_config

        reporter = mock.Mock()
        with mock.patch("cairn.dispatcher.prompting.load_prompt", return_value="CURRENT") as fallback:
            prompt = load_prompt_from_execution_config({}, "reason.md", "mock", reporter)

        self.assertEqual(prompt, "CURRENT")
        fallback.assert_called_once_with("mock", "reason.md")
        reporter.emit_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
