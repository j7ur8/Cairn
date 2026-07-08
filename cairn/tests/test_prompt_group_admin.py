from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


def _write_phase_prompts(root: Path) -> None:
    from cairn.dispatcher.prompts.layout import PROMPT_PHASES
    from cairn.shared.config.constants import DEFAULT_PROMPT_REQUIRED_TOKENS

    common = {
        "bootstrap": ("bootstrap.md", "bootstrap_conclude.md", "FILE_OUTPUTS.md"),
        "explore": ("explore.md", "explore_conclude.md", "FILE_OUTPUTS.md"),
        "reason": ("reason.md", "FILE_OUTPUTS.md"),
    }
    for phase in PROMPT_PHASES:
        (root / phase / "common").mkdir(parents=True, exist_ok=True)
        (root / phase / "roles").mkdir(parents=True, exist_ok=True)
        (root / phase / "instruction").mkdir(parents=True, exist_ok=True)
        instruction = f"# Instructions\n\nCurrent Cairn task family: `{{task_type}}`.\n{{selected role prompt}}\n{{selected_mcp_ids}}\n"
        for name in ("Instruction.md", "AGENTS.md", "CLAUDE.md"):
            (root / phase / "instruction" / name).write_text(instruction, encoding="utf-8")
        for role_id in ("cypher-ctf-operator", "cypher-pentest-operator"):
            (root / phase / "roles" / f"{role_id}.md").write_text(f"{phase} {role_id} role\n", encoding="utf-8")
        for name in common[phase]:
            tokens = " ".join(DEFAULT_PROMPT_REQUIRED_TOKENS.get(name, ()))
            (root / phase / "common" / name).write_text(f"{name}\n{tokens}\n", encoding="utf-8")


class PromptGroupAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _write_phase_prompts(self.root)
        (self.root / "config.resources.yaml").write_text(
            yaml.safe_dump(
                {
                    "capabilities": {
                        "mcp_servers": [],
                        "skills": [{"id": "skill-a", "name": "Skill A", "source_path": str(self.root)}],
                    },
                    "roles": [
                        {
                            "id": "cypher-ctf-operator",
                            "name": "CTF Operator",
                            "default_skill_ids": ["skill-a"],
                        },
                        {
                            "id": "cypher-pentest-operator",
                            "name": "Pentest Operator",
                            "default_skill_ids": [],
                            "available": False,
                        },
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        import cairn.server.routers.prompt_groups as prompt_groups

        self.router = prompt_groups
        self.root_patch = mock.patch.object(prompt_groups, "_prompts_root", return_value=self.root.resolve())
        self.resources_path_patch = mock.patch.object(
            prompt_groups,
            "resources_yaml_path",
            return_value=self.root / "config.resources.yaml",
        )
        self.files_patch = mock.patch("cairn.server.execution_config.prompt_snapshot.resources.files", return_value=self.root)
        self.runtime_root_patch = mock.patch(
            "cairn.dispatcher.tasks.instruction_files.runtime_instruction_templates_root",
            return_value=self.root.resolve(),
        )
        for patcher in (self.root_patch, self.resources_path_patch, self.files_patch, self.runtime_root_patch):
            patcher.start()

    def tearDown(self) -> None:
        for patcher in (self.runtime_root_patch, self.files_patch, self.resources_path_patch, self.root_patch):
            patcher.stop()
        self.tmp.cleanup()

    def test_read_prompt_group_returns_phase_first_common_resources(self) -> None:
        result = self.router.read_prompt_group()

        self.assertEqual(result["prompt_group"], "phase-first")
        self.assertEqual(
            set(result["prompts"]),
            {
                "bootstrap.md",
                "bootstrap_conclude.md",
                "bootstrap/FILE_OUTPUTS.md",
                "explore.md",
                "explore_conclude.md",
                "explore/FILE_OUTPUTS.md",
                "reason.md",
                "reason/FILE_OUTPUTS.md",
            },
        )
        resources = {resource["path"]: resource for resource in result["resources"]}
        self.assertEqual(resources["bootstrap.md"]["phase"], "bootstrap")
        self.assertEqual(resources["explore.md"]["category"], "common")
        self.assertEqual(resources["explore/FILE_OUTPUTS.md"]["phase"], "explore")
        self.assertEqual(resources["reason/FILE_OUTPUTS.md"]["logical_name"], "FILE_OUTPUTS.md")
        self.assertRegex(result["prompt_sha256"]["reason.md"], r"^[0-9a-f]{64}$")
        self.assertRegex(result["prompts_sha256"], r"^[0-9a-f]{64}$")

    def test_common_prompt_save_validates_required_placeholders(self) -> None:
        from fastapi import HTTPException
        from cairn.shared.config.constants import DEFAULT_PROMPT_REQUIRED_TOKENS

        original = (self.root / "reason" / "common" / "reason.md").read_text(encoding="utf-8")
        with self.assertRaises(HTTPException) as cm:
            self.router.update_prompt_template_legacy("reason.md", self.router.PromptGroupTemplateUpdate(content="missing\n"))
        self.assertEqual(cm.exception.status_code, 400)
        self.assertEqual((self.root / "reason" / "common" / "reason.md").read_text(encoding="utf-8"), original)

        content = "updated\n" + " ".join(DEFAULT_PROMPT_REQUIRED_TOKENS["reason.md"]) + "\n"
        result = self.router.update_prompt_template("reason.md", self.router.PromptGroupTemplateUpdate(content=content))
        self.assertEqual(result["prompts"]["reason.md"], content)
        self.assertEqual((self.root / "reason" / "common" / "reason.md").read_text(encoding="utf-8"), content)

    def test_role_prompts_are_phase_specific_and_update_default_skills(self) -> None:
        body = self.router.RolePromptSettingsUpdateRequest(
            content="updated explore role\n",
            phase="explore",
            default_skill_ids=["skill-a"],
        )
        with mock.patch.object(self.router, "save_resources_data") as save:
            save.side_effect = lambda data: (self.root / "config.resources.yaml").write_text(
                yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
            )
            result = self.router.update_role_prompt_settings("cypher-ctf-operator", body)

        key = "explore/roles/cypher-ctf-operator.md"
        self.assertEqual(result["roles"][key], "updated explore role\n")
        self.assertEqual((self.root / key).read_text(encoding="utf-8"), "updated explore role\n")
        self.assertEqual(result["role_metadata"][key]["phase"], "explore")
        self.assertEqual(result["role_metadata"][key]["default_skill_ids"], ["skill-a"])
        self.assertEqual((self.root / "bootstrap" / "roles" / "cypher-ctf-operator.md").read_text(encoding="utf-8"), "bootstrap cypher-ctf-operator role\n")

    def test_instruction_prompt_save_regenerates_agent_files(self) -> None:
        before = self.router.read_prompt_instruction_previews()
        bootstrap_before = next(phase for phase in before.phases if phase.phase == "bootstrap")
        old_sha = bootstrap_before.files[0].sha256
        body = self.router.PromptGroupTemplateUpdate(content="# Instructions\n\nUpdated {task_type}.\n")

        after = self.router.update_prompt_instruction_preview("bootstrap", "Instruction.md", body)

        for name in ("Instruction.md", "AGENTS.md", "CLAUDE.md"):
            self.assertEqual((self.root / "bootstrap" / "instruction" / name).read_text(encoding="utf-8"), body.content)
        bootstrap_after = next(phase for phase in after.phases if phase.phase == "bootstrap")
        self.assertEqual([file.path for file in bootstrap_after.files], ["Instruction.md"])
        self.assertNotEqual(old_sha, bootstrap_after.files[0].sha256)

    def test_invalid_prompt_paths_are_rejected(self) -> None:
        from fastapi import HTTPException

        for name in ("../x.md", "/x.md", "roles/x.md", "unknown.md"):
            with self.subTest(name=name):
                with self.assertRaises(HTTPException):
                    self.router.update_prompt_template(name, self.router.PromptGroupTemplateUpdate(content="x"))
        for name in ("../x.md", "roles/x.md", "bootstrap/roles/x.txt", "invalid/roles/x.md"):
            with self.subTest(name=name):
                with self.assertRaises(HTTPException):
                    self.router.update_role_prompt(name, self.router.PromptGroupTemplateUpdate(content="x"))
        with self.assertRaises(HTTPException):
            self.router.update_prompt_instruction_preview(
                "bootstrap",
                "AGENTS.md",
                self.router.PromptGroupTemplateUpdate(content="x"),
            )

    def test_inject_task_instructions_uses_phase_instruction_files(self) -> None:
        from cairn.dispatcher.tasks.instruction_files import inject_task_instructions
        from cairn.dispatcher.workers.base import WorkerExecutionContext

        (self.root / "bootstrap" / "instruction" / "AGENTS.md").write_text(
            "Template marker {project_id} {task_instance_id} {selected role prompt}\n",
            encoding="utf-8",
        )

        class Writer:
            def __init__(self):
                self.files = {}

            def write_text_file(self, _container_name, path, content):
                self.files[path] = content

        writer = Writer()
        paths = inject_task_instructions(
            container_manager=writer,
            container_name="runner",
            project=None,
            project_id="proj",
            task_type="bootstrap",
            task_instance_id="task",
            role_instructions="Role text.",
            capability_instructions="Capability text.",
            context=WorkerExecutionContext(mcp_servers=[{"id": "cairn-resources"}]),
        )

        self.assertEqual(writer.files[paths.agents_md_path], "Template marker proj task Role text.\n")


class DockerComposePromptVolumeTests(unittest.TestCase):
    def test_cairn_server_mounts_phase_first_prompt_root(self) -> None:
        compose = yaml.safe_load((_REPO / "docker-compose.yaml").read_text(encoding="utf-8"))
        volumes = compose["services"]["cairn-server"]["volumes"]

        self.assertIn(
            "./cairn/src/cairn/dispatcher/prompts:/cairn/src/cairn/dispatcher/prompts",
            volumes,
        )
        self.assertNotIn(
            "./cairn/src/cairn/dispatcher/prompts/default:/cairn/src/cairn/dispatcher/prompts/default",
            volumes,
        )


class PromptSettingsFrontendTests(unittest.TestCase):
    def test_frontend_filters_by_phase_and_category_and_saves_role_or_instruction(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required to execute frontend state helper")

        prompts_path = _REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "app" / "state-prompts.js"
        script = f"""
            import {{ pathToFileURL }} from 'node:url';

            const {{ createPromptsState }} = await import(pathToFileURL({json.dumps(str(prompts_path))}).href);
            const state = createPromptsState();
            const calls = [];
            state.showToast = (message, type = 'success') => calls.push(['toast', type, message]);
            state.api = async (method, path, body) => {{
              calls.push([method, path, body || null]);
              if (path === '/prompt-templates') return {{
                prompt_names: ['bootstrap.md', 'explore.md'],
                prompts: {{ 'bootstrap.md': 'bootstrap prompt', 'explore.md': 'explore prompt' }},
                prompt_sha256: {{ 'bootstrap.md': 'boot-sha', 'explore.md': 'explore-sha' }},
                prompts_sha256: 'set-sha',
                resources: [
                  {{ phase: 'bootstrap', category: 'common', path: 'bootstrap.md', logical_name: 'bootstrap.md', content: 'bootstrap prompt', sha256: 'boot-sha', writable: true }},
                  {{ phase: 'explore', category: 'common', path: 'explore.md', logical_name: 'explore.md', content: 'explore prompt', sha256: 'explore-sha', writable: true }},
                ],
              }};
              if (path === '/role-prompts') return {{
                role_names: ['explore/roles/cypher-ctf-operator.md'],
                roles: {{ 'explore/roles/cypher-ctf-operator.md': 'explore role' }},
                role_sha256: {{ 'explore/roles/cypher-ctf-operator.md': 'role-sha' }},
                role_metadata: {{ 'explore/roles/cypher-ctf-operator.md': {{ role_id: 'cypher-ctf-operator', phase: 'explore', name: 'CTF Operator', default_skill_ids: ['skill-a'], available: true }} }},
                resources: [{{ phase: 'explore', category: 'roles', path: 'explore/roles/cypher-ctf-operator.md', logical_name: 'cypher-ctf-operator.md', content: 'explore role', sha256: 'role-sha', writable: true, role_metadata: {{ role_id: 'cypher-ctf-operator', phase: 'explore', name: 'CTF Operator', default_skill_ids: ['skill-a'], available: true }} }}],
              }};
              if (path === '/capabilities/catalog') return [{{ id: 'skill-a', name: 'Skill A', kind: 'skill' }}];
              if (path === '/prompt-instruction-previews') return {{
                phases: [{{ phase: 'explore', task_instance_id: '{{task_instance_id}}', files: [{{ path: 'Instruction.md', content: 'instruction', sha256: 'inst-sha', writable: true }}] }}],
                resources: [{{ phase: 'explore', category: 'instruction', path: 'Instruction.md', logical_name: 'Instruction.md', content: 'instruction', sha256: 'inst-sha', writable: true }}],
              }};
              if (path === '/prompt-templates/templates/explore.md') return {{
                prompt_names: ['bootstrap.md', 'explore.md'],
                prompts: {{ 'bootstrap.md': 'bootstrap prompt', 'explore.md': body.content }},
                prompt_sha256: {{ 'bootstrap.md': 'boot-sha', 'explore.md': 'new-explore-sha' }},
                prompts_sha256: 'new-set-sha',
                resources: [
                  {{ phase: 'bootstrap', category: 'common', path: 'bootstrap.md', logical_name: 'bootstrap.md', content: 'bootstrap prompt', sha256: 'boot-sha', writable: true }},
                  {{ phase: 'explore', category: 'common', path: 'explore.md', logical_name: 'explore.md', content: body.content, sha256: 'new-explore-sha', writable: true }},
                ],
              }};
              if (path === '/roles/admin/cypher-ctf-operator/prompt-settings') return {{
                role_names: ['explore/roles/cypher-ctf-operator.md'],
                roles: {{ 'explore/roles/cypher-ctf-operator.md': body.content }},
                role_sha256: {{ 'explore/roles/cypher-ctf-operator.md': 'new-role-sha' }},
                role_metadata: {{ 'explore/roles/cypher-ctf-operator.md': {{ role_id: 'cypher-ctf-operator', phase: 'explore', name: 'CTF Operator', default_skill_ids: body.default_skill_ids, available: true }} }},
                resources: [],
              }};
              if (path === '/prompt-instruction-previews/explore/Instruction.md') return {{
                phases: [{{ phase: 'explore', task_instance_id: '{{task_instance_id}}', files: [{{ path: 'Instruction.md', content: body.content, sha256: 'new-inst-sha', writable: true }}] }}],
                resources: [{{ phase: 'explore', category: 'instruction', path: 'Instruction.md', logical_name: 'Instruction.md', content: body.content, sha256: 'new-inst-sha', writable: true }}],
              }};
              throw new Error(`unexpected api call: ${{method}} ${{path}}`);
            }};

            await state.loadPromptGroup();
            state.selectPromptPhase('explore');
            const phaseResources = state.promptEditorResources();
            const phaseKeys = phaseResources.map(resource => resource.key);
            const groups = phaseResources
              .filter((resource, index) => state.promptShowResourceGroup(resource, index))
              .map(resource => resource.groupLabel);
            const role = phaseResources.find(resource => resource.type === 'role');
            const common = phaseResources.find(resource => resource.type === 'prompt');
            state.selectPromptTemplate(common);
            state.promptEditorContent = 'updated explore prompt';
            await state.savePromptTemplate();
            const commonContentAfterSave = state.promptEditorContent;
            state.selectPromptTemplate(role);
            state.promptEditorContent = 'updated role';
            state.promptRoleRequiredSkillIds = ['skill-a'];
            await state.savePromptTemplate();
            const isRole = state.promptSelectedIsRole();
            const instruction = state.promptEditorResources().find(resource => resource.type === 'runtime');
            state.selectPromptTemplate(instruction);
            state.promptEditorContent = 'updated instruction';
            await state.savePromptTemplate();

            console.log(JSON.stringify({{
              calls,
              phaseKeys,
              groups,
              roleLabel: state.promptResourceDisplayName(role),
              instructionLabel: state.promptResourceDisplayName(instruction),
              isRole,
              commonContentAfterSave,
              finalContent: state.promptEditorContent,
            }}));
        """

        completed = subprocess.run([node, "--input-type=module", "-e", script], check=True, capture_output=True, text=True)
        result = json.loads(completed.stdout)
        api_calls = [call for call in result["calls"] if call[0] in {"GET", "PUT", "POST", "DELETE"}]

        self.assertEqual(
            result["phaseKeys"],
            [
                "explore/common/explore.md",
                "explore/roles/cypher-ctf-operator.md",
                "explore/instruction/Instruction.md",
            ],
        )
        self.assertEqual(result["groups"], ["Common Prompt", "Role Prompt", "Instruction Prompt"])
        self.assertEqual(result["roleLabel"], "cypher-ctf-operator")
        self.assertEqual(result["instructionLabel"], "Instruction.md")
        self.assertTrue(result["isRole"])
        self.assertEqual(result["commonContentAfterSave"], "updated explore prompt")
        common_save = next(call for call in api_calls if call[1] == "/prompt-templates/templates/explore.md")
        role_save = next(call for call in api_calls if call[1] == "/roles/admin/cypher-ctf-operator/prompt-settings")
        instruction_save = next(call for call in api_calls if call[1] == "/prompt-instruction-previews/explore/Instruction.md")
        self.assertEqual(common_save[2]["content"], "updated explore prompt")
        self.assertEqual(role_save[2]["phase"], "explore")
        self.assertEqual(instruction_save[2]["content"], "updated instruction")
        self.assertEqual(result["finalContent"], "updated instruction")

    def test_settings_contains_phase_prompt_editor_controls(self) -> None:
        view = (_REPO / "cairn" / "src" / "cairn" / "server" / "partials" / "view_settings.html").read_text(
            encoding="utf-8"
        )
        prompts = (_REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "app" / "state-prompts.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("selectPromptPhase('bootstrap')", view)
        self.assertIn("selectPromptPhase('explore')", view)
        self.assertIn("selectPromptPhase('reason')", view)
        self.assertIn("Common Prompt", prompts)
        self.assertIn("Role Prompt", prompts)
        self.assertIn("Instruction Prompt", prompts)
        self.assertIn("resource.groupLabel", view)
        self.assertIn("promptActivePhase", prompts)
        self.assertNotIn("promptActiveCategory", prompts)
        self.assertNotIn("selectPromptCategory", prompts)
        self.assertNotIn("selectPromptCategory", view)
        self.assertIn('data-testid="role-required-skills"', view)
        self.assertIn('x-show="promptSelectedIsRole()"', view)


if __name__ == "__main__":
    unittest.main()
