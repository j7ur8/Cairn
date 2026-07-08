from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))
_PROMPTS_DIR = _REPO / "cairn" / "src" / "cairn" / "dispatcher" / "prompts"


def _common_prompt_path(name: str) -> Path:
    if "/" in name:
        phase, filename = name.split("/", 1)
        return _PROMPTS_DIR / phase / "common" / filename
    phase = "bootstrap"
    if name.startswith("explore"):
        phase = "explore"
    elif name.startswith("reason"):
        phase = "reason"
    return _PROMPTS_DIR / phase / "common" / name


def _common_prompt(name: str) -> str:
    return _common_prompt_path(name).read_text(encoding="utf-8")


def _write_phase_snapshot(root: Path, prompts: dict[str, str]) -> None:
    for name, content in prompts.items():
        target = root / _common_prompt_path(name).relative_to(_PROMPTS_DIR)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


class PromptSnapshotTests(unittest.TestCase):
    def test_prompt_markdown_files_have_only_task_h1(self) -> None:
        for path in _PROMPTS_DIR.glob("*/common/*.md"):
            with self.subTest(path=path.relative_to(_PROMPTS_DIR).as_posix()):
                h1s = [
                    line.removeprefix("# ").strip()
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.startswith("# ") and not line.startswith("## ")
                ]
                self.assertEqual(h1s, ["Task"])

    def test_default_templates_keep_role_out_of_phase_prompts(self) -> None:
        bootstrap = _common_prompt("bootstrap.md")
        explore = _common_prompt("explore.md")
        reason = _common_prompt("reason.md")
        bootstrap_conclude = _common_prompt("bootstrap_conclude.md")
        explore_conclude = _common_prompt("explore_conclude.md")

        self.assertIn("# Task\n", bootstrap)
        self.assertIn("# Task\n", explore)
        self.assertIn("# Task\n", reason)
        self.assertIn("Active prompt: bootstrap.md", bootstrap.splitlines()[:3])
        self.assertIn("Active prompt: explore.md", explore.splitlines()[:3])
        self.assertIn("Active prompt: reason.md", reason.splitlines()[:3])
        self.assertNotIn("{role_instructions}", bootstrap)
        self.assertNotIn("{role_instructions}", explore)
        self.assertNotIn("{role_instructions}", reason)
        self.assertNotIn("{role_instructions}", bootstrap_conclude)
        self.assertNotIn("{role_instructions}", explore_conclude)

    def test_default_explore_uses_plain_text_sentinel_output(self) -> None:
        explore = _common_prompt("explore.md")

        output_requirements = explore.split("## Output Requirements", 1)[1].split("### Rules", 1)[0]
        self.assertIn("32173462130721312360912", output_requirements)
        self.assertIn("plain text", output_requirements)
        self.assertIn("Do not output JSON", output_requirements)
        self.assertNotIn("Return only one raw JSON object", output_requirements)

    def test_default_explore_prompt_is_assigned_intent_investigation(self) -> None:
        explore = _common_prompt("explore.md")
        task_section = explore.split("## Output Requirements", 1)[0]

        for text in (
            "Explore investigates the assigned Current Intent.",
            "Use Fact View as confirmed context.",
            "Use Full Graph only as fallback",
            "Use Current Intent as the starting point",
            "Current Intent Description as the requested exploration scope",
            "newly confirmed incremental facts",
            "Do not make Reason-phase decisions, propose new intents",
        ):
            self.assertIn(text, task_section)
        for text in (
            "satisfies Goal",
            "Goal has been achieved",
            "data.complete",
        ):
            self.assertNotIn(text, explore)

    def test_default_explore_prompts_preserve_partial_negative_scope(self) -> None:
        explore = _common_prompt("explore.md")
        explore_conclude = _common_prompt("explore_conclude.md")

        for name, prompt in (("explore.md", explore), ("explore_conclude.md", explore_conclude)):
            with self.subTest(name=name):
                self.assertIn("tested method or scope", prompt)
                self.assertIn("sibling", prompt)
                self.assertIn("whole-family", prompt)

    def test_default_explore_conclude_is_read_only_fact_conclusion(self) -> None:
        prompt = _common_prompt("explore_conclude.md")
        from cairn.server.routers.prompt_groups import read_prompt_instruction_previews

        previews = read_prompt_instruction_previews()
        phase_files = {
            phase.phase: {file.path: file.content for file in phase.files}
            for phase in previews.phases
        }
        instruction = phase_files["explore"]["Instruction.md"]

        for text in (
            "Fact View",
            "Full Graph",
            "confirmed Explore facts",
            "Do not collect new information",
            "tested method or scope",
            "concrete failure limit",
        ):
            self.assertIn(text, prompt)
        for text in (
            "Explore_conclude summarizes already confirmed Explore facts",
            "Use only files directly cited by the Fact View or Full Graph",
            "Do not scan for additional files or evidence",
            "must not run commands",
            "wait for unfinished work",
        ):
            self.assertIn(text, instruction)

    def test_default_bootstrap_task_sets_discovery_only_boundary(self) -> None:
        bootstrap = _common_prompt("bootstrap.md")
        task_section = bootstrap.split("## Output Requirements", 1)[0]

        self.assertIn("Active prompt: bootstrap.md", task_section.splitlines()[:3])
        self.assertIn("# Task", task_section.splitlines()[:4])
        self.assertNotIn("{role_instructions}", bootstrap)
        self.assertNotIn("{capability_instructions}", bootstrap)
        self.assertIn(
            "Use Origin as the starting point. Use Goal only to understand the requested success condition. Treat Hints as unverified guidance;",
            task_section,
        )
        self.assertIn("initial target information", task_section)
        self.assertIn("confirmed target profile facts", task_section)
        self.assertIn("actual vulnerability exploitation", task_section)
        self.assertNotIn("SQLi, XSS, RCE", task_section)
        self.assertNotIn("authentication-bypass", task_section)
        self.assertNotIn("high-volume directory-enumeration", task_section)
        self.assertNotIn("static, provided, and publicly observable facts", task_section)
        self.assertNotIn("satisfies Goal", task_section)
        self.assertNotIn("complete", task_section)
        self.assertNotIn("CTF", task_section)
        self.assertNotIn("flag", task_section)
        self.assertNotIn("summarize", bootstrap)
        self.assertNotIn("not continuing exploration", bootstrap)
        self.assertNotIn("execute any command except read", bootstrap)
        self.assertNotIn("information_api.json", task_section)
        self.assertNotIn("information_leak.json", task_section)
        output_requirements = bootstrap.split("## Output Requirements", 1)[1].split("## Rules", 1)[0]
        self.assertIn("confirmed target profile facts", output_requirements)
        self.assertNotIn("fact summary", output_requirements)
        self.assertIn("## Output Requirements", bootstrap)
        self.assertIn("## Context", bootstrap)

    def test_runtime_instruction_preview_owns_phase_boundaries(self) -> None:
        from cairn.server.routers.prompt_groups import read_prompt_instruction_previews

        bootstrap = _common_prompt("bootstrap.md")
        explore = _common_prompt("explore.md")
        previews = read_prompt_instruction_previews()
        phase_files = {
            phase.phase: {file.path: file.content for file in phase.files}
            for phase in previews.phases
        }

        self.assertNotIn("SQLi, XSS, RCE", bootstrap)
        self.assertNotIn("Stop when evidence is sufficient", explore)
        self.assertIn("Bootstrap collects initial target information from Origin, Goal, and Hints.", phase_files["bootstrap"]["Instruction.md"])
        self.assertIn("Do not perform actual vulnerability exploitation.", phase_files["bootstrap"]["Instruction.md"])
        self.assertIn("Bootstrap_conclude summarizes already confirmed bootstrap facts.", phase_files["bootstrap"]["Instruction.md"])
        self.assertIn(
            "Do not execute any command except read. Do not need to wait for unfinished tasks or commands. Do not continue exploration and Do not generate an action plan.",
            phase_files["bootstrap"]["Instruction.md"],
        )
        self.assertIn("Do not continue information collection during bootstrap_conclude.", phase_files["bootstrap"]["Instruction.md"])
        self.assertNotIn("high-volume enumeration", phase_files["bootstrap"]["Instruction.md"])
        self.assertNotIn("brute force", phase_files["bootstrap"]["Instruction.md"])
        self.assertNotIn("exploit-chain payloading", phase_files["bootstrap"]["Instruction.md"])
        self.assertIn("Stop when evidence is sufficient", phase_files["explore"]["Instruction.md"])
        self.assertIn("Reason does not execute tools", phase_files["reason"]["Instruction.md"])

    def test_bootstrap_instruction_variants_are_synchronized(self) -> None:
        instruction_dir = _PROMPTS_DIR / "bootstrap" / "instruction"
        contents = {
            name: (instruction_dir / name).read_text(encoding="utf-8")
            for name in ("Instruction.md", "AGENTS.md", "CLAUDE.md")
        }

        self.assertEqual(contents["Instruction.md"], contents["AGENTS.md"])
        self.assertEqual(contents["Instruction.md"], contents["CLAUDE.md"])

    def test_explore_and_reason_instruction_variants_are_synchronized(self) -> None:
        for phase in ("explore", "reason"):
            with self.subTest(phase=phase):
                instruction_dir = _PROMPTS_DIR / phase / "instruction"
                contents = {
                    name: (instruction_dir / name).read_text(encoding="utf-8")
                    for name in ("Instruction.md", "AGENTS.md", "CLAUDE.md")
                }

                self.assertEqual(contents["Instruction.md"], contents["AGENTS.md"])
                self.assertEqual(contents["Instruction.md"], contents["CLAUDE.md"])

    def test_default_phase_prompts_use_legacy_context_sections(self) -> None:
        forbidden = (
            "Project Context",
            "project context file",
            "project.md",
            "phase.md",
            "capabilities.md",
            "policy.json",
        )

        prompts = {
            name: _common_prompt(name)
            for name in ("bootstrap.md", "bootstrap_conclude.md", "explore.md", "explore_conclude.md", "reason.md")
        }

        for name, prompt in prompts.items():
            with self.subTest(name=name):
                for text in forbidden:
                    self.assertNotIn(text, prompt)

        for name in ("bootstrap.md", "bootstrap_conclude.md"):
            with self.subTest(name=name):
                context = prompts[name].split("## Context\n", 1)[1].strip()
                self.assertEqual(
                    context,
                    "### Origin\n"
                    "```\n"
                    "{origin}\n"
                    "```\n\n"
                    "### Goal\n"
                    "```\n"
                    "{goal}\n"
                    "```\n\n"
                    "### Hints\n"
                    "```\n"
                    "{hints}\n"
                    "```",
                )

        for name in ("explore.md", "explore_conclude.md"):
            with self.subTest(name=name):
                context = prompts[name].split("## Context\n", 1)[1].strip()
                self.assertEqual(
                    context,
                    "### Fact View\n"
                    "```\n"
                    "{fact_view}\n"
                    "```\n\n"
                    "### Full Graph\n"
                    "```\n"
                    "{full_graph}\n"
                    "```\n\n"
                    "### Current Intent\n"
                    "```\n"
                    "{intent_id}\n"
                    "```\n\n"
                    "### Current Intent Description\n"
                    "```\n"
                    "{intent_description}\n"
                    "```",
                )
                self.assertNotIn("{origin}", prompts[name])
                self.assertNotIn("{goal}", prompts[name])
                self.assertNotIn("{hints}", prompts[name])

        reason_context = prompts["reason.md"].split("### Context\n", 1)[1].strip()
        self.assertEqual(
            reason_context,
            "#### Fact View\n"
            "```\n"
            "{fact_view}\n"
            "```\n\n"
            "#### Full Graph\n"
            "```\n"
            "{full_graph}\n"
            "```\n\n"
            "#### Valid facts\n"
            "```\n"
            "{fact_ids}\n"
            "```\n\n"
            "#### Open Intents\n"
            "```\n"
            "{open_intents}\n"
            "```",
        )
        self.assertNotIn("{origin}", prompts["reason.md"])
        self.assertNotIn("{goal}", prompts["reason.md"])
        self.assertNotIn("{hints}", prompts["reason.md"])

    def test_role_prompts_keep_project_semantics_without_bootstrap_protocol(self) -> None:
        roles_dirs = [
            _PROMPTS_DIR / "bootstrap" / "roles",
            _PROMPTS_DIR / "explore" / "roles",
            _PROMPTS_DIR / "reason" / "roles",
        ]
        cases = {
            "cypher-pentest-operator.md": {
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
            "cypher-vuln-researcher.md": {
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

        for roles_dir in roles_dirs:
            for name, expected in cases.items():
                with self.subTest(path=(roles_dir / name).relative_to(_PROMPTS_DIR).as_posix()):
                    role = (roles_dir / name).read_text(encoding="utf-8")
                    for text in expected["include"]:
                        self.assertIn(text, role)
                    for text in expected["exclude"]:
                        self.assertNotIn(text, role)

    def test_bootstrap_ctf_role_supports_initial_collection_without_reason_completion(self) -> None:
        role = (_PROMPTS_DIR / "bootstrap" / "roles" / "cypher-ctf-operator.md").read_text(encoding="utf-8")

        for text in (
            "bootstrap stage",
            "Determine the type",
            "web, pwn, reverse, crypto, forensics, misc",
            "public routes",
            "page source",
            "linked JavaScript/CSS/assets",
            "API clients",
            "binaries, protocols, artifacts, encodings, algorithms",
            "actual vulnerability exploitation",
        ):
            self.assertIn(text, role)
        for text in (
            "requested flag, proof, or challenge-specific success condition",
            "evidence that explains why the result satisfies the goal",
            "complete",
        ):
            self.assertNotIn(text, role)

    def test_reason_ctf_role_keeps_goal_satisfaction_semantics(self) -> None:
        role = (_PROMPTS_DIR / "reason" / "roles" / "cypher-ctf-operator.md").read_text(encoding="utf-8")

        self.assertIn("requested flag, proof, or challenge-specific success condition", role)
        self.assertIn("evidence that explains why the result satisfies the goal", role)

    def test_explore_ctf_role_excludes_reason_goal_satisfaction_semantics(self) -> None:
        role = (_PROMPTS_DIR / "explore" / "roles" / "cypher-ctf-operator.md").read_text(encoding="utf-8")

        self.assertIn("During Explore, investigate only the assigned Current Intent", role)
        self.assertIn("flag or proof is directly exposed", role)
        for text in (
            "requested flag, proof, or challenge-specific success condition",
            "evidence that explains why the result satisfies the goal",
        ):
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
        reason = _common_prompt("reason.md")

        output_requirements = reason.split("## Output Requirements", 1)[1].split("### Rules", 1)[0]
        self.assertIn("32173462130721312360912", output_requirements)
        self.assertIn("84913462130721312360912", output_requirements)
        self.assertIn("00003462130721312360912", output_requirements)
        self.assertIn('{"accepted": true, "data": {"complete"', output_requirements)
        self.assertIn('{"accepted": true, "data": {"intents"', output_requirements)
        self.assertIn('{"accepted": true, "data": {}}', output_requirements)
        self.assertNotIn("Return only one raw JSON object", output_requirements)

    def test_default_reason_excludes_capability_instructions_placeholder(self) -> None:
        reason = _common_prompt("reason.md")

        self.assertNotIn("{capability_instructions}", reason)
        self.assertNotIn("{role_instructions}", reason)
        self.assertNotIn("{hints}", reason)
        self.assertIn("{fact_view}", reason)
        self.assertIn("{full_graph}", reason)
        self.assertIn("{fact_ids}", reason)
        self.assertIn("{open_intents}", reason)
        self.assertIn("{max_intents}", reason)

    def test_default_reason_prompt_is_graph_only_decision(self) -> None:
        reason = _common_prompt("reason.md")

        for text in (
            "Reason evaluates the confirmed graph and emits one protocol decision.",
            "Use Fact View as the primary graph state.",
            "Use Full Graph only as fallback",
            "Decide exactly one state",
            "Goal satisfied",
            "propose new high-value intents",
            "wait with no new intent",
            "Do not execute tools, collect new information, or continue exploration.",
            "Valid facts",
            "Open Intents",
            "{max_intents}",
        ):
            self.assertIn(text, reason)
        for marker in (
            "32173462130721312360912",
            "84913462130721312360912",
            "00003462130721312360912",
        ):
            self.assertIn(marker, reason)
        self.assertIn("data.complete.from` must come only from `Valid facts", reason)

    def test_default_bootstrap_and_explore_exclude_capability_instructions(self) -> None:
        bootstrap = _common_prompt("bootstrap.md")
        explore = _common_prompt("explore.md")

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
            _write_phase_snapshot(Path(tmp), prompts)
            with mock.patch("cairn.server.execution_config.prompt_snapshot.resources.files") as files:
                files.return_value = Path(tmp)
                changed = load_prompt_snapshot()

        self.assertEqual(
            set(first["prompts"]),
            {"bootstrap.md", "bootstrap_conclude.md", "explore.md", "explore_conclude.md", "reason.md"},
        )
        self.assertNotIn("prompt_group", first)
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
