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

    def test_default_templates_keep_role_out_of_phase_prompts(self) -> None:
        default_dir = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts" / "default"

        bootstrap = (default_dir / "bootstrap.md").read_text(encoding="utf-8")
        explore = (default_dir / "explore.md").read_text(encoding="utf-8")
        reason = (default_dir / "reason.md").read_text(encoding="utf-8")
        bootstrap_conclude = (default_dir / "bootstrap_conclude.md").read_text(encoding="utf-8")
        explore_conclude = (default_dir / "explore_conclude.md").read_text(encoding="utf-8")

        self.assertIn("# Task\n", bootstrap)
        self.assertIn("# Task\n", explore)
        self.assertIn("# Task\n", reason)
        self.assertNotIn("{role_instructions}", bootstrap)
        self.assertNotIn("{role_instructions}", explore)
        self.assertNotIn("{role_instructions}", reason)
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

    def test_default_explore_conclude_is_read_only_fact_conclusion(self) -> None:
        default_dir = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts" / "default"
        prompt = (default_dir / "explore_conclude.md").read_text(encoding="utf-8")

        for text in (
            "read-only fact-conclusion phase",
            "already confirmed facts from this session",
            "Fact View",
            "Full Graph",
            "Do not use Bash",
            "MCP tools",
            "browser or network access",
            "scanners",
            "Do not create new payloads",
            "continue exploration",
            "wait for tasks",
            "Use Read only",
            "Do not scan for additional files or evidence",
        ):
            self.assertIn(text, prompt)

    def test_default_bootstrap_task_sets_discovery_only_boundary(self) -> None:
        default_dir = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts" / "default"
        bootstrap = (default_dir / "bootstrap.md").read_text(encoding="utf-8")
        task_section = bootstrap.split("## Output Requirements", 1)[0]

        self.assertTrue(task_section.strip().startswith("# Task"))
        self.assertNotIn("{role_instructions}", bootstrap)
        self.assertNotIn("{capability_instructions}", bootstrap)
        self.assertIn("target discovery and profiling only", task_section)
        self.assertIn("task-local phase boundary", task_section)
        self.assertIn("Build a concise target profile", task_section)
        self.assertIn("static, provided, and publicly observable facts", task_section)
        self.assertIn("technology and runtime fingerprints", task_section)
        self.assertNotIn("SQLi, XSS, RCE", task_section)
        self.assertNotIn("authentication-bypass", task_section)
        self.assertNotIn("high-volume directory-enumeration", task_section)
        self.assertNotIn("CTF", task_section)
        self.assertNotIn("flag", task_section)
        self.assertNotIn("summarize", bootstrap)
        self.assertNotIn("not continuing exploration", bootstrap)
        self.assertNotIn("execute any command except read", bootstrap)
        self.assertNotIn("page source", task_section)
        self.assertNotIn("response headers", task_section)
        self.assertNotIn("JavaScript", task_section)
        self.assertNotIn("CSS", task_section)
        self.assertNotIn("public paths", task_section)
        self.assertNotIn("form behavior", task_section)
        self.assertNotIn("information_api.json", task_section)
        self.assertNotIn("information_leak.json", task_section)
        output_requirements = bootstrap.split("## Output Requirements", 1)[1].split("## Rules", 1)[0]
        self.assertIn("confirmed target profile facts", output_requirements)
        self.assertNotIn("fact summary", output_requirements)
        self.assertIn("## Output Requirements", bootstrap)
        self.assertIn("## Context", bootstrap)

    def test_runtime_instruction_preview_owns_phase_boundaries(self) -> None:
        from cairn.server.routers.prompt_groups import read_prompt_instruction_previews

        default_dir = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts" / "default"
        bootstrap = (default_dir / "bootstrap.md").read_text(encoding="utf-8")
        explore = (default_dir / "explore.md").read_text(encoding="utf-8")
        previews = read_prompt_instruction_previews()
        phase_files = {
            phase.phase: {file.path: file.content for file in phase.files}
            for phase in previews.phases
        }

        self.assertNotIn("SQLi, XSS, RCE", bootstrap)
        self.assertNotIn("Stop when evidence is sufficient", explore)
        self.assertIn("high-volume enumeration", phase_files["bootstrap"]["context/phase.md"])
        self.assertIn("Stop when evidence is sufficient", phase_files["explore"]["context/phase.md"])
        self.assertIn("Reason does not execute tools", phase_files["reason"]["context/phase.md"])

    def test_role_prompts_keep_project_semantics_without_bootstrap_protocol(self) -> None:
        roles_dir = _REPO / "capabilities" / "roles"
        cases = {
            "cypher-ctf-operator/ROLE.md": {
                "include": [
                    "This is a CTF project.",
                    "requested flag, proof, or challenge-specific success condition",
                    "evidence that explains why the result satisfies the goal",
                    "likely challenge categories",
                    "do not force a single classification",
                    "mixed",
                    "combine multiple areas",
                    "public entrypoints",
                    "For web challenges",
                    "page source",
                    "linked JavaScript/CSS/assets",
                    "API clients",
                    "leaked information",
                    "For pwn, reverse, crypto, forensics, or misc challenges",
                    "binaries, protocols, artifacts, encodings, algorithms",
                    "If a flag or proof is directly exposed",
                ],
                "exclude": [
                    "Bootstrap is target discovery only",
                    "Allowed bootstrap activity includes",
                    "vulnerability verification, SQLi/XSS/RCE payloading",
                    "information_api.json",
                    "information_leak.json",
                    "JavaScript reverse engineering",
                    "deep exploitation",
                    "use skill",
                    "infromation",
                ],
            },
            "cypher-pentest-operator/ROLE.md": {
                "include": [
                    "This is an authorized penetration testing project.",
                    "rules of engagement",
                    "confirmed impact",
                    "public surface",
                    "authentication and authorization boundaries",
                    "tenant boundaries",
                ],
                "exclude": [
                    "Bootstrap is target discovery only",
                    "Allowed bootstrap activity includes",
                    "minimally disruptive public-surface checks",
                    "vulnerability verification, SQLi/XSS/RCE payloading",
                    "deep exploitation",
                ],
            },
            "cypher-vuln-researcher/ROLE.md": {
                "include": [
                    "This is a vulnerability research, PoC development, or root-cause analysis project.",
                    "deterministic repro and root-cause evidence",
                    "component, version",
                    "reachable repro surface",
                    "affected code path",
                    "likely fix area",
                ],
                "exclude": [
                    "Bootstrap is target discovery only",
                    "Allowed bootstrap activity includes",
                    "vulnerability verification, SQLi/XSS/RCE payloading",
                    "broad fuzzing",
                    "high-volume testing",
                ],
            },
        }

        for name, expected in cases.items():
            with self.subTest(name=name):
                role = (roles_dir / name).read_text(encoding="utf-8")
                for text in expected["include"]:
                    self.assertIn(text, role)
                for text in expected["exclude"]:
                    self.assertNotIn(text, role)

    def test_existing_skill_owns_ctf_web_js_output_contract(self) -> None:
        skill_dir = _REPO / "capabilities" / "skills" / "ctf-web-js-analysis"
        skill = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        output_contract = (skill_dir / "references" / "output-contract.md").read_text(encoding="utf-8")

        self.assertIn("information_api.json", skill)
        self.assertIn("information_leak.json", skill)
        self.assertIn("Every finding must include `source`, `evidence`, and `value`", skill)
        for text in [
            "information_api.json",
            "information_leak.json",
            "`apis`: array of API finding objects",
            "`leaks`: array of leak finding objects",
            "`value` is not evidence confidence",
        ]:
            self.assertIn(text, output_contract)

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
        self.assertNotIn("{role_instructions}", reason)
        self.assertIn("{hints}", reason)
        self.assertIn("{fact_view}", reason)
        self.assertIn("{full_graph}", reason)
        self.assertIn("{fact_ids}", reason)
        self.assertIn("{open_intents}", reason)
        self.assertIn("{max_intents}", reason)

    def test_default_bootstrap_and_explore_exclude_capability_instructions(self) -> None:
        default_dir = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts" / "default"
        bootstrap = (default_dir / "bootstrap.md").read_text(encoding="utf-8")
        explore = (default_dir / "explore.md").read_text(encoding="utf-8")

        for name, prompt in (("bootstrap.md", bootstrap), ("explore.md", explore)):
            with self.subTest(name=name):
                self.assertNotIn("{capability_instructions}", prompt)
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
