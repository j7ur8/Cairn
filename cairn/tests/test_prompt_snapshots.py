from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


class PromptSnapshotTests(unittest.TestCase):
    def test_prompt_markdown_files_have_only_task_h1(self) -> None:
        prompts_dir = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts"

        for path in prompts_dir.rglob("*.md"):
            with self.subTest(path=path.relative_to(prompts_dir).as_posix()):
                h1s = [
                    line.removeprefix("# ").strip()
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.startswith("# ") and not line.startswith("## ")
                ]
                self.assertEqual(h1s, ["Task"])

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
        self.assertIn("{role_instructions}", bootstrap.split("## Output Requirements", 1)[0])
        self.assertIn("{role_instructions}", explore.split("## Output Requirements", 1)[0])
        self.assertIn("{role_instructions}", reason.split("## Output Requirements", 1)[0])
        self.assertNotIn("{role_instructions}", bootstrap_conclude)
        self.assertNotIn("{role_instructions}", explore_conclude)

    def test_default_explore_uses_plain_text_sentinel_output(self) -> None:
        default_dir = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts" / "default"
        explore = (default_dir / "explore.md").read_text(encoding="utf-8")

        output_requirements = explore.split("## Output Requirements", 1)[1].split("## Rules", 1)[0]
        self.assertIn("32173462130721312360912", output_requirements)
        self.assertIn("plain text", output_requirements)
        self.assertIn("Do not output JSON", output_requirements)
        self.assertNotIn("Return only one raw JSON object", output_requirements)

    def test_default_explore_prompts_preserve_partial_negative_scope(self) -> None:
        default_dir = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts" / "default"
        explore = (default_dir / "explore.md").read_text(encoding="utf-8")
        explore_conclude = (default_dir / "explore_conclude.md").read_text(encoding="utf-8")

        for name, prompt in (("explore.md", explore), ("explore_conclude.md", explore_conclude)):
            with self.subTest(name=name):
                self.assertIn("tested method or scope", prompt)
                self.assertIn("sibling", prompt)
                self.assertIn("whole-family", prompt)

    def test_default_bootstrap_task_sets_discovery_only_boundary(self) -> None:
        default_dir = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts" / "default"
        bootstrap = (default_dir / "bootstrap.md").read_text(encoding="utf-8")
        task_section = bootstrap.split("## Output Requirements", 1)[0]

        self.assertTrue(task_section.strip().startswith("# Task\n{role_instructions}"))
        self.assertIn("{role_instructions}", bootstrap)
        self.assertIn("{capability_instructions}", bootstrap)
        self.assertIn("target discovery only", task_section)
        self.assertIn("Do not perform vulnerability probing or exploitation", task_section)
        self.assertIn("SQLi, XSS, RCE", task_section)
        self.assertIn("authentication-bypass", task_section)
        self.assertIn("high-volume directory-enumeration", task_section)
        self.assertIn("## Output Requirements", bootstrap)
        self.assertIn("## Context", bootstrap)

    def test_role_prompts_contain_bootstrap_guidance(self) -> None:
        roles_dir = _REPO / "capabilities" / "roles"
        cases = {
            "cypher-ctf-operator/ROLE.md": [
                "bounded initial challenge triage",
                "do not force a single classification",
                "mixed",
                "combine multiple areas",
                "frontend static analysis and JavaScript reverse engineering",
                "information_api.json",
                "information_leak.json",
                "public entrypoints",
                "If a flag or proof is directly exposed",
                "deep exploitation",
                "vulnerability verification, SQLi/XSS/RCE payloading",
                "During bootstrap, include only static or publicly visible evidence",
            ],
            "cypher-pentest-operator/ROLE.md": [
                "bounded, scope-aware reconnaissance",
                "rules of engagement",
                "authentication and authorization boundaries",
                "minimally disruptive public-surface checks",
                "Bootstrap is target discovery only",
                "vulnerability verification, SQLi/XSS/RCE payloading",
            ],
            "cypher-vuln-researcher/ROLE.md": [
                "bounded target-identification",
                "component, version",
                "reachable repro surface",
                "broad fuzzing",
                "Bootstrap is target discovery only",
                "vulnerability verification, SQLi/XSS/RCE payloading",
            ],
        }

        for name, expected in cases.items():
            with self.subTest(name=name):
                role = (roles_dir / name).read_text(encoding="utf-8")
                for text in expected:
                    self.assertIn(text, role)

    def test_default_reason_uses_marker_gated_output(self) -> None:
        default_dir = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts" / "default"
        reason = (default_dir / "reason.md").read_text(encoding="utf-8")

        output_requirements = reason.split("## Output Requirements", 1)[1].split("### Rules", 1)[0]
        self.assertIn("32173462130721312360912", output_requirements)
        self.assertIn("84913462130721312360912", output_requirements)
        self.assertIn("00003462130721312360912", output_requirements)
        self.assertIn('{"accepted": true, "data": {"complete"', output_requirements)
        self.assertIn('{"accepted": true, "data": {"intents"', output_requirements)
        self.assertIn('{"accepted": true, "data": {}}', output_requirements)
        self.assertNotIn("Return only one raw JSON object", output_requirements)

    def test_default_reason_excludes_capability_instructions_placeholder(self) -> None:
        default_dir = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts" / "default"
        reason = (default_dir / "reason.md").read_text(encoding="utf-8")

        self.assertNotIn("{capability_instructions}", reason)
        self.assertIn("{role_instructions}", reason)
        self.assertIn("{fact_view}", reason)
        self.assertIn("{full_graph}", reason)
        self.assertIn("{fact_ids}", reason)
        self.assertIn("{open_intents}", reason)
        self.assertIn("{max_intents}", reason)

    def test_default_bootstrap_and_explore_use_capability_instructions_only(self) -> None:
        default_dir = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts" / "default"
        bootstrap = (default_dir / "bootstrap.md").read_text(encoding="utf-8")
        explore = (default_dir / "explore.md").read_text(encoding="utf-8")

        for name, prompt in (("bootstrap.md", bootstrap), ("explore.md", explore)):
            with self.subTest(name=name):
                self.assertIn("{capability_instructions}", prompt)
                self.assertNotIn("{remote_" "support_instructions}", prompt)
                h1s = [line for line in prompt.splitlines() if line.startswith("# ") and not line.startswith("## ")]
                self.assertEqual(h1s, ["# Task"])

    def test_load_prompt_snapshot_hash_changes_with_content(self) -> None:
        from cairn.server.execution_config.prompt_snapshot import load_prompt_snapshot

        first = load_prompt_snapshot()
        original = first["prompts"]["reason.md"]
        prompts = dict(first["prompts"])
        prompts["reason.md"] = f"{original}\nextra"
        with tempfile.TemporaryDirectory() as tmp:
            group_dir = Path(tmp) / "default"
            group_dir.mkdir()
            for name, content in prompts.items():
                (group_dir / name).write_text(content, encoding="utf-8")
            with mock.patch("cairn.server.execution_config.prompt_snapshot.resources.files") as files:
                files.return_value.joinpath.side_effect = lambda group: Path(tmp) / group
                changed = load_prompt_snapshot()

        self.assertEqual(
            set(first["prompts"]),
            {"bootstrap.md", "bootstrap_conclude.md", "explore.md", "explore_conclude.md", "reason.md", "FILE_OUTPUTS.md"},
        )
        self.assertEqual(first["prompt_group"], "default")
        self.assertNotEqual(first["prompts_sha256"], changed["prompts_sha256"])

    def test_load_prompt_from_execution_config_uses_snapshot(self) -> None:
        from cairn.dispatcher.prompting import load_prompt_from_execution_config

        reporter = mock.Mock()
        prompt = load_prompt_from_execution_config(
            {"prompt_snapshot": {"prompts": {"reason.md": "SNAPSHOT"}}},
            "reason.md",
            reporter,
        )

        self.assertEqual(prompt, "SNAPSHOT")
        reporter.emit_error.assert_not_called()

    def test_load_prompt_from_execution_config_falls_back_and_warns(self) -> None:
        from cairn.dispatcher.prompting import load_prompt_from_execution_config

        reporter = mock.Mock()
        with mock.patch("cairn.dispatcher.prompting.load_prompt", return_value="CURRENT") as fallback:
            prompt = load_prompt_from_execution_config({}, "reason.md", reporter)

        self.assertEqual(prompt, "CURRENT")
        fallback.assert_called_once_with("reason.md")
        reporter.emit_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
