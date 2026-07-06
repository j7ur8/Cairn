from __future__ import annotations

import json
import shutil
import subprocess
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
    (group_dir / "FILE_OUTPUTS.md").write_text(overrides.get("FILE_OUTPUTS.md", "file outputs\n"), encoding="utf-8")


class PromptGroupAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _write_prompt_group(self.root, "default")
        import cairn.server.routers.prompt_groups as prompt_groups

        self.router = prompt_groups
        self.root_patch = mock.patch.object(prompt_groups, "_prompts_root", return_value=self.root.resolve())
        self.root_patch.start()
        self.resources_path_patch = mock.patch.object(
            prompt_groups,
            "resources_yaml_path",
            return_value=self.root / "config.resources.yaml",
        )
        self.resources_path_patch.start()
        self.files_patch = mock.patch("cairn.server.execution_config.prompt_snapshot.resources.files")
        files = self.files_patch.start()
        files.return_value.joinpath.side_effect = lambda group: self.root / group

    def tearDown(self) -> None:
        self.files_patch.stop()
        self.resources_path_patch.stop()
        self.root_patch.stop()
        self.tmp.cleanup()

    def test_read_prompt_group_returns_templates_and_hashes(self) -> None:
        roles_dir = self.root / "default" / "roles"
        roles_dir.mkdir()
        (roles_dir / "redteam.md").write_text("extra role prompt\n", encoding="utf-8")

        result = self.router.read_prompt_group()

        self.assertEqual(result["prompt_group"], "default")
        self.assertEqual(
            set(result["prompts"]),
            {
                "FILE_OUTPUTS.md",
                "bootstrap.md",
                "bootstrap_conclude.md",
                "explore.md",
                "explore_conclude.md",
                "reason.md",
                "roles/redteam.md",
            },
        )
        self.assertIn("roles/redteam.md", result["prompt_names"])
        self.assertRegex(result["prompt_sha256"]["reason.md"], r"^[0-9a-f]{64}$")
        self.assertRegex(result["prompt_sha256"]["roles/redteam.md"], r"^[0-9a-f]{64}$")
        self.assertRegex(result["prompts_sha256"], r"^[0-9a-f]{64}$")

    def test_read_prompt_group_rejects_group_missing_file_outputs(self) -> None:
        from fastapi import HTTPException

        (self.root / "default" / "FILE_OUTPUTS.md").unlink()

        with self.assertRaises(HTTPException) as cm:
            self.router.read_prompt_group()

        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("missing resource: FILE_OUTPUTS.md", cm.exception.detail)

    def test_read_role_prompts_returns_markdown_files_and_hashes(self) -> None:
        import yaml

        role_root = self.root / "capabilities" / "roles"
        (role_root / "cypher-ctf-operator").mkdir(parents=True)
        (role_root / "cypher-ctf-operator" / "ROLE.md").write_text("ctf role\n", encoding="utf-8")
        (role_root / "cypher-pentest-operator").mkdir(parents=True)
        (role_root / "cypher-pentest-operator" / "ROLE.md").write_text("pentest role\n", encoding="utf-8")
        (self.root / "config.resources.yaml").write_text(
            yaml.safe_dump(
                {
                    "capabilities": {"mcp_servers": [], "skills": []},
                    "roles": [
                        {
                            "id": "cypher-ctf-operator",
                            "name": "CTF Operator",
                            "source_path": "capabilities/roles/cypher-ctf-operator/ROLE.md",
                            "default_skill_ids": ["cypher-ctf"],
                            "available": True,
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

        result = self.router.read_role_prompts()

        self.assertEqual(result["role_names"], ["cypher-ctf-operator/ROLE.md", "cypher-pentest-operator/ROLE.md"])
        self.assertEqual(result["roles"]["cypher-ctf-operator/ROLE.md"], "ctf role\n")
        self.assertRegex(result["role_sha256"]["cypher-ctf-operator/ROLE.md"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            result["role_metadata"]["cypher-ctf-operator/ROLE.md"],
            {
                "role_id": "cypher-ctf-operator",
                "name": "CTF Operator",
                "default_skill_ids": ["cypher-ctf"],
                "available": True,
            },
        )
        self.assertFalse(result["role_metadata"]["cypher-pentest-operator/ROLE.md"]["available"])

    def test_read_role_prompts_metadata_prefers_source_path(self) -> None:
        import yaml

        role_root = self.root / "capabilities" / "roles"
        (role_root / "custom-location").mkdir(parents=True)
        (role_root / "custom-location" / "ROLE.md").write_text("custom role\n", encoding="utf-8")
        (self.root / "config.resources.yaml").write_text(
            yaml.safe_dump(
                {
                    "capabilities": {"mcp_servers": [], "skills": []},
                    "roles": [
                        {
                            "id": "role-id",
                            "name": "Role Name",
                            "source_path": "capabilities/roles/custom-location/ROLE.md",
                            "default_skill_ids": ["skill1"],
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        result = self.router.read_role_prompts()

        self.assertIn("custom-location/ROLE.md", result["role_metadata"])
        self.assertEqual(result["role_metadata"]["custom-location/ROLE.md"]["role_id"], "role-id")
        self.assertNotIn("role-id/ROLE.md", result["role_metadata"])

    def test_read_role_prompts_reports_metadata_load_error(self) -> None:
        role_root = self.root / "capabilities" / "roles" / "cypher-ctf-operator"
        role_root.mkdir(parents=True)
        (role_root / "ROLE.md").write_text("ctf role\n", encoding="utf-8")
        (self.root / "config.resources.yaml").write_text("roles: [\n", encoding="utf-8")

        result = self.router.read_role_prompts()

        self.assertEqual(result["roles"]["cypher-ctf-operator/ROLE.md"], "ctf role\n")
        self.assertEqual(result["role_metadata"], {})
        self.assertIn("failed to load role metadata", result["role_metadata_error"])

    def test_update_role_prompt_writes_file_and_updates_hash(self) -> None:
        role_root = self.root / "capabilities" / "roles" / "cypher-ctf-operator"
        role_root.mkdir(parents=True)
        target = role_root / "ROLE.md"
        target.write_text("original role prompt\n", encoding="utf-8")

        before = self.router.read_role_prompts()
        body = self.router.PromptGroupTemplateUpdate(content="updated role prompt\n")
        after = self.router.update_role_prompt("cypher-ctf-operator/ROLE.md", body)

        self.assertEqual(target.read_text(encoding="utf-8"), "updated role prompt\n")
        self.assertEqual(after["roles"]["cypher-ctf-operator/ROLE.md"], "updated role prompt\n")
        self.assertNotEqual(before["role_sha256"]["cypher-ctf-operator/ROLE.md"], after["role_sha256"]["cypher-ctf-operator/ROLE.md"])

    def test_update_role_prompt_settings_updates_prompt_and_default_skills(self) -> None:
        import yaml

        role_root = self.root / "capabilities" / "roles" / "cypher-ctf-operator"
        role_root.mkdir(parents=True)
        target = role_root / "ROLE.md"
        target.write_text("original role prompt\n", encoding="utf-8")
        (self.root / "skill-a").mkdir()
        (self.root / "skill-b").mkdir()
        (self.root / "config.resources.yaml").write_text(
            yaml.safe_dump(
                {
                    "capabilities": {
                        "mcp_servers": [],
                        "skills": [
                            {"id": "skill-a", "name": "Skill A", "source_path": str(self.root / "skill-a")},
                            {"id": "skill-b", "name": "Skill B", "source_path": str(self.root / "skill-b")},
                        ],
                    },
                    "roles": [
                        {
                            "id": "cypher-ctf-operator",
                            "name": "CTF Operator",
                            "source_path": "capabilities/roles/cypher-ctf-operator/ROLE.md",
                            "default_skill_ids": ["skill-b"],
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        body = self.router.RolePromptSettingsUpdateRequest(
            content="updated role prompt\n",
            default_skill_ids=[" skill-a ", "skill-a", "", "skill-b"],
        )

        with mock.patch.object(self.router, "save_resources_data") as save:
            save.side_effect = lambda data: (self.root / "config.resources.yaml").write_text(
                yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
            )
            after = self.router.update_role_prompt_settings("cypher-ctf-operator", body)

        data = yaml.safe_load((self.root / "config.resources.yaml").read_text(encoding="utf-8"))
        self.assertEqual(target.read_text(encoding="utf-8"), "updated role prompt\n")
        self.assertEqual(data["roles"][0]["default_skill_ids"], ["skill-a", "skill-b"])
        self.assertEqual(after["roles"]["cypher-ctf-operator/ROLE.md"], "updated role prompt\n")
        self.assertEqual(
            after["role_metadata"]["cypher-ctf-operator/ROLE.md"]["default_skill_ids"],
            ["skill-a", "skill-b"],
        )

    def test_update_role_prompt_settings_rolls_back_prompt_when_yaml_save_fails(self) -> None:
        import yaml
        from fastapi import HTTPException

        role_root = self.root / "capabilities" / "roles" / "cypher-ctf-operator"
        role_root.mkdir(parents=True)
        target = role_root / "ROLE.md"
        target.write_text("original role prompt\n", encoding="utf-8")
        (self.root / "skill-a").mkdir()
        (self.root / "config.resources.yaml").write_text(
            yaml.safe_dump(
                {
                    "capabilities": {
                        "mcp_servers": [],
                        "skills": [{"id": "skill-a", "name": "Skill A", "source_path": str(self.root / "skill-a")}],
                    },
                    "roles": [
                        {
                            "id": "cypher-ctf-operator",
                            "name": "CTF Operator",
                            "source_path": "capabilities/roles/cypher-ctf-operator/ROLE.md",
                            "default_skill_ids": [],
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        original_yaml = (self.root / "config.resources.yaml").read_text(encoding="utf-8")
        body = self.router.RolePromptSettingsUpdateRequest(content="updated role prompt\n", default_skill_ids=["skill-a"])

        def write_then_fail(data):
            (self.root / "config.resources.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            raise HTTPException(503, "reload failed")

        with mock.patch.object(self.router, "save_resources_data", side_effect=write_then_fail):
            with self.assertRaises(HTTPException) as cm:
                self.router.update_role_prompt_settings("cypher-ctf-operator", body)

        self.assertEqual(cm.exception.status_code, 503)
        self.assertEqual(target.read_text(encoding="utf-8"), "original role prompt\n")
        self.assertEqual((self.root / "config.resources.yaml").read_text(encoding="utf-8"), original_yaml)

    def test_update_role_prompt_settings_rejects_unknown_role_or_skill_without_writing(self) -> None:
        import yaml
        from fastapi import HTTPException

        role_root = self.root / "capabilities" / "roles" / "cypher-ctf-operator"
        role_root.mkdir(parents=True)
        target = role_root / "ROLE.md"
        target.write_text("original role prompt\n", encoding="utf-8")
        (self.root / "config.resources.yaml").write_text(
            yaml.safe_dump(
                {
                    "capabilities": {"mcp_servers": [], "skills": []},
                    "roles": [
                        {
                            "id": "cypher-ctf-operator",
                            "name": "CTF Operator",
                            "source_path": "capabilities/roles/cypher-ctf-operator/ROLE.md",
                            "default_skill_ids": [],
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        original_yaml = (self.root / "config.resources.yaml").read_text(encoding="utf-8")

        for role_id, skill_ids, status in (
            ("missing-role", [], 404),
            ("cypher-ctf-operator", ["missing-skill"], 400),
        ):
            with self.subTest(role_id=role_id, skill_ids=skill_ids):
                with self.assertRaises(HTTPException) as cm:
                    self.router.update_role_prompt_settings(
                        role_id,
                        self.router.RolePromptSettingsUpdateRequest(
                            content="updated role prompt\n",
                            default_skill_ids=skill_ids,
                        ),
                    )
                self.assertEqual(cm.exception.status_code, status)
                self.assertEqual(target.read_text(encoding="utf-8"), "original role prompt\n")
                self.assertEqual((self.root / "config.resources.yaml").read_text(encoding="utf-8"), original_yaml)

    def test_update_prompt_template_writes_file_and_updates_hash(self) -> None:
        from cairn.shared.config.constants import DEFAULT_PROMPT_REQUIRED_TOKENS

        before = self.router.read_prompt_group()
        content = "updated reason\n" + " ".join(DEFAULT_PROMPT_REQUIRED_TOKENS["reason.md"]) + "\n"
        body = self.router.PromptGroupTemplateUpdate(content=content)
        after = self.router.update_prompt_template_legacy("reason.md", body)

        self.assertEqual((self.root / "default" / "reason.md").read_text(encoding="utf-8"), content)
        self.assertEqual(after["prompts"]["reason.md"], content)
        self.assertNotEqual(before["prompt_sha256"]["reason.md"], after["prompt_sha256"]["reason.md"])
        self.assertNotEqual(before["prompts_sha256"], after["prompts_sha256"])

    def test_update_nested_prompt_template_writes_file_and_updates_hash(self) -> None:
        roles_dir = self.root / "default" / "roles"
        roles_dir.mkdir()
        (roles_dir / "redteam.md").write_text("original role prompt\n", encoding="utf-8")

        before = self.router.read_prompt_group()
        content = "updated role prompt\n"
        body = self.router.PromptGroupTemplateUpdate(content=content)
        after = self.router.update_prompt_template("roles/redteam.md", body)

        self.assertEqual((roles_dir / "redteam.md").read_text(encoding="utf-8"), content)
        self.assertEqual(after["prompts"]["roles/redteam.md"], content)
        self.assertNotEqual(before["prompt_sha256"]["roles/redteam.md"], after["prompt_sha256"]["roles/redteam.md"])
        self.assertNotEqual(before["prompts_sha256"], after["prompts_sha256"])

    def test_extra_prompt_template_does_not_require_core_placeholders(self) -> None:
        roles_dir = self.root / "default" / "roles"
        roles_dir.mkdir()
        (roles_dir / "redteam.md").write_text("original role prompt\n", encoding="utf-8")
        body = self.router.PromptGroupTemplateUpdate(content="no placeholders required here\n")

        after = self.router.update_prompt_template("roles/redteam.md", body)

        self.assertEqual(after["prompts"]["roles/redteam.md"], "no placeholders required here\n")

    def test_file_outputs_template_is_writable_without_placeholder_validation(self) -> None:
        body = self.router.PromptGroupTemplateUpdate(content="updated file outputs\n")

        after = self.router.update_prompt_template_legacy("FILE_OUTPUTS.md", body)

        self.assertEqual((self.root / "default" / "FILE_OUTPUTS.md").read_text(encoding="utf-8"), "updated file outputs\n")
        self.assertEqual(after["prompts"]["FILE_OUTPUTS.md"], "updated file outputs\n")

    def test_update_missing_required_placeholder_fails_without_writing(self) -> None:
        from fastapi import HTTPException

        original = (self.root / "default" / "reason.md").read_text(encoding="utf-8")
        body = self.router.PromptGroupTemplateUpdate(content="{graph_yaml}\n")

        with self.assertRaises(HTTPException) as cm:
            self.router.update_prompt_template_legacy("reason.md", body)

        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("missing placeholders", cm.exception.detail)
        self.assertEqual((self.root / "default" / "reason.md").read_text(encoding="utf-8"), original)

    def test_invalid_template_name_is_rejected(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as name_cm:
            self.router.update_prompt_template_legacy(
                "../reason.md",
                self.router.PromptGroupTemplateUpdate(content="x"),
            )

        self.assertEqual(name_cm.exception.status_code, 400)

    def test_nested_template_invalid_paths_are_rejected(self) -> None:
        from fastapi import HTTPException

        for name in ("../x.md", "/x.md", "roles\\x.md", "roles/x.txt"):
            with self.subTest(name=name):
                with self.assertRaises(HTTPException) as cm:
                    self.router.update_prompt_template(
                        name,
                        self.router.PromptGroupTemplateUpdate(content="x"),
                    )
                self.assertEqual(cm.exception.status_code, 400)

    def test_invalid_role_prompt_paths_are_rejected(self) -> None:
        from fastapi import HTTPException

        for name in ("../x.md", "/x.md", "roles\\x.md", "roles/x.txt", "missing.md"):
            with self.subTest(name=name):
                with self.assertRaises(HTTPException) as cm:
                    self.router.update_role_prompt(name, self.router.PromptGroupTemplateUpdate(content="x"))
                self.assertIn(cm.exception.status_code, {400, 404})


class PromptSettingsFrontendTests(unittest.TestCase):
    def test_prompt_resource_display_names_are_sidebar_only_labels(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required to execute frontend state helper")

        prompts_path = _REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "app" / "state-prompts.js"
        script = f"""
            import {{ pathToFileURL }} from 'node:url';

            const {{ createPromptsState }} = await import(pathToFileURL({json.dumps(str(prompts_path))}).href);
            const state = createPromptsState();
            state.promptTemplateDetail = {{
              prompt_names: ['reason.md', 'roles/redteam.md'],
              prompts: {{
                'reason.md': 'reason prompt',
                'roles/redteam.md': 'redteam prompt',
              }},
              prompt_sha256: {{
                'reason.md': 'reason-sha',
                'roles/redteam.md': 'redteam-sha',
              }},
              prompts_sha256: 'group-sha',
            }};
            state.rolePromptDetail = {{
              role_names: ['cypher-ctf-operator/ROLE.md', 'legacy/custom.md', 'custom.md'],
              roles: {{
                'cypher-ctf-operator/ROLE.md': 'ctf role',
                'legacy/custom.md': 'legacy role',
                'custom.md': 'custom role',
              }},
              role_sha256: {{
                'cypher-ctf-operator/ROLE.md': 'role-sha',
                'legacy/custom.md': 'legacy-sha',
                'custom.md': 'custom-sha',
              }},
              role_metadata: {{
                'cypher-ctf-operator/ROLE.md': {{
                  role_id: 'cypher-ctf-operator',
                  name: 'CTF Operator',
                  default_skill_ids: ['cypher-ctf'],
                  available: true,
                }},
              }},
            }};
            state.promptCapabilityCatalog = [
              {{ id: 'cypher-ctf', name: 'CTF', kind: 'skill' }},
              {{ id: 'kali-server-mcp', name: 'Kali', kind: 'mcp_server' }},
            ];

            const resources = state.promptEditorResources();
            const roleResource = resources.find(resource => resource.path === 'cypher-ctf-operator/ROLE.md');
            state.promptTemplateNames = resources.map(resource => resource.key);
            state.promptTemplateSelected = roleResource.key;
            state.syncPromptRoleRequiredSkills();

            console.log(JSON.stringify({{
              labels: Object.fromEntries(resources.map(resource => [resource.key, state.promptResourceDisplayName(resource)])),
              roleKey: roleResource.key,
              rolePath: roleResource.path,
              selectedContent: state.promptSelectedResourceContent(),
              selectedSha: state.promptTemplateSha(),
              routePath: state.promptTemplateRoutePath(roleResource.path),
              isRole: state.promptSelectedIsRole(),
              roleName: state.promptSelectedRoleName(),
              selectedSkillIds: state.promptRoleRequiredSkillIds,
              skillOptions: state.promptAvailableSkillOptions().map(item => item.id),
              canEditRequiredSkills: state.promptRoleCanEditRequiredSkills(),
              groups: resources.filter((resource, index) => state.promptShowResourceGroup(resource, index)).map(resource => resource.groupLabel),
            }}));
        """

        completed = subprocess.run(
            [node, "--input-type=module", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["labels"]["prompts/reason.md"], "reason.md")
        self.assertEqual(result["labels"]["prompts/roles/redteam.md"], "redteam.md")
        self.assertEqual(result["labels"]["roles/cypher-ctf-operator/ROLE.md"], "cypher-ctf-operator")
        self.assertEqual(result["labels"]["roles/legacy/custom.md"], "legacy")
        self.assertEqual(result["labels"]["roles/custom.md"], "custom.md")
        self.assertEqual(result["roleKey"], "roles/cypher-ctf-operator/ROLE.md")
        self.assertEqual(result["rolePath"], "cypher-ctf-operator/ROLE.md")
        self.assertEqual(result["selectedContent"], "ctf role")
        self.assertEqual(result["selectedSha"], "role-sha")
        self.assertEqual(result["routePath"], "cypher-ctf-operator/ROLE.md")
        self.assertTrue(result["isRole"])
        self.assertEqual(result["roleName"], "CTF Operator")
        self.assertEqual(result["selectedSkillIds"], ["cypher-ctf"])
        self.assertEqual(result["skillOptions"], ["cypher-ctf"])
        self.assertTrue(result["canEditRequiredSkills"])
        self.assertEqual(result["groups"], ["Prompt Templates", "Role Prompts"])

    def test_prompt_save_updates_role_default_skills_only_for_role_prompts(self) -> None:
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
              if (path === '/roles/admin/cypher-ctf-operator/prompt-settings') {{
                return {{
                  role_names: ['cypher-ctf-operator/ROLE.md'],
                  roles: {{ 'cypher-ctf-operator/ROLE.md': body.content }},
                  role_sha256: {{ 'cypher-ctf-operator/ROLE.md': 'new-role-sha' }},
                  role_metadata: {{ 'cypher-ctf-operator/ROLE.md': {{ role_id: 'cypher-ctf-operator', name: 'CTF Operator', default_skill_ids: body.default_skill_ids, available: true }} }},
                }};
              }}
              if (path === '/prompt-templates/templates/reason.md') {{
                return {{
                  prompt_names: ['reason.md'],
                  prompts: {{ 'reason.md': body.content }},
                  prompt_sha256: {{ 'reason.md': 'new-prompt-sha' }},
                  prompts_sha256: 'new-set-sha',
                }};
              }}
              throw new Error(`unexpected api call: ${{method}} ${{path}}`);
            }};
            state.promptTemplateDetail = {{
              prompt_names: ['reason.md'],
              prompts: {{ 'reason.md': 'reason prompt' }},
              prompt_sha256: {{ 'reason.md': 'reason-sha' }},
              prompts_sha256: 'set-sha',
            }};
            state.rolePromptDetail = {{
              role_names: ['cypher-ctf-operator/ROLE.md'],
              roles: {{ 'cypher-ctf-operator/ROLE.md': 'ctf role' }},
              role_sha256: {{ 'cypher-ctf-operator/ROLE.md': 'role-sha' }},
              role_metadata: {{ 'cypher-ctf-operator/ROLE.md': {{ role_id: 'cypher-ctf-operator', name: 'CTF Operator', default_skill_ids: ['old-skill'], available: true }} }},
            }};
            state.promptTemplateNames = state.promptEditorResources().map(item => item.key);

            state.promptTemplateSelected = 'roles/cypher-ctf-operator/ROLE.md';
            state.promptEditorContent = 'updated role';
            state.promptRoleRequiredSkillIds = ['skill-a', 'skill-b'];
            await state.savePromptTemplate();

            state.promptTemplateSelected = 'prompts/reason.md';
            state.promptEditorContent = 'updated reason';
            await state.savePromptTemplate();

            console.log(JSON.stringify({{
              calls,
              roleSkillIds: state.rolePromptDetail.role_metadata['cypher-ctf-operator/ROLE.md'].default_skill_ids,
            }}));
        """

        completed = subprocess.run(
            [node, "--input-type=module", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        api_calls = [call for call in result["calls"] if call[0] in {"GET", "PUT", "POST", "DELETE"}]
        self.assertEqual(api_calls[0][1], "/roles/admin/cypher-ctf-operator/prompt-settings")
        self.assertEqual(api_calls[0][2], {"content": "updated role", "default_skill_ids": ["skill-a", "skill-b"]})
        self.assertEqual(api_calls[1][1], "/prompt-templates/templates/reason.md")
        self.assertEqual(
            [call[1] for call in api_calls].count("/roles/admin/cypher-ctf-operator/default-skills"),
            0,
        )
        self.assertEqual(result["roleSkillIds"], ["skill-a", "skill-b"])

    def test_prompt_save_failure_keeps_role_editor_state(self) -> None:
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
              throw new Error('save failed');
            }};
            state.promptTemplateDetail = {{ prompt_names: [], prompts: {{}}, prompt_sha256: {{}}, prompts_sha256: 'set-sha' }};
            state.rolePromptDetail = {{
              role_names: ['cypher-ctf-operator/ROLE.md'],
              roles: {{ 'cypher-ctf-operator/ROLE.md': 'ctf role' }},
              role_sha256: {{ 'cypher-ctf-operator/ROLE.md': 'role-sha' }},
              role_metadata: {{ 'cypher-ctf-operator/ROLE.md': {{ role_id: 'cypher-ctf-operator', name: 'CTF Operator', default_skill_ids: ['old-skill'], available: true }} }},
            }};
            state.promptTemplateNames = state.promptEditorResources().map(item => item.key);
            state.promptTemplateSelected = 'roles/cypher-ctf-operator/ROLE.md';
            state.promptEditorContent = 'unsaved role';
            state.promptRoleRequiredSkillIds = ['skill-a'];

            await state.savePromptTemplate();

            console.log(JSON.stringify({{
              calls,
              editorContent: state.promptEditorContent,
              skillIds: state.promptRoleRequiredSkillIds,
            }}));
        """

        completed = subprocess.run(
            [node, "--input-type=module", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        api_calls = [call for call in result["calls"] if call[0] in {"GET", "PUT", "POST", "DELETE"}]
        self.assertEqual(api_calls[0][1], "/roles/admin/cypher-ctf-operator/prompt-settings")
        self.assertEqual(result["editorContent"], "unsaved role")
        self.assertEqual(result["skillIds"], ["skill-a"])

    def test_prompt_required_skills_disabled_when_metadata_errors(self) -> None:
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
              throw new Error('should not call api');
            }};
            state.promptTemplateDetail = {{ prompt_names: [], prompts: {{}}, prompt_sha256: {{}}, prompts_sha256: 'set-sha' }};
            state.rolePromptDetail = {{
              role_names: ['cypher-ctf-operator/ROLE.md'],
              roles: {{ 'cypher-ctf-operator/ROLE.md': 'ctf role' }},
              role_sha256: {{ 'cypher-ctf-operator/ROLE.md': 'role-sha' }},
              role_metadata: {{}},
              role_metadata_error: 'failed to load role metadata: yaml error',
            }};
            state.promptTemplateNames = state.promptEditorResources().map(item => item.key);
            state.promptTemplateSelected = 'roles/cypher-ctf-operator/ROLE.md';
            state.promptEditorContent = 'unsaved role';
            state.promptRoleRequiredSkillIds = ['skill-a'];

            await state.savePromptTemplate();

            console.log(JSON.stringify({{
              calls,
              canEdit: state.promptRoleCanEditRequiredSkills(),
              error: state.promptRoleMetadataError(),
              editorContent: state.promptEditorContent,
              skillIds: state.promptRoleRequiredSkillIds,
            }}));
        """

        completed = subprocess.run(
            [node, "--input-type=module", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        api_calls = [call for call in result["calls"] if call[0] in {"GET", "PUT", "POST", "DELETE"}]
        self.assertEqual(api_calls, [])
        self.assertFalse(result["canEdit"])
        self.assertIn("failed to load role metadata", result["error"])
        self.assertEqual(result["editorContent"], "unsaved role")
        self.assertEqual(result["skillIds"], ["skill-a"])

    def test_settings_contains_prompt_editor_controls(self) -> None:
        view = (_REPO / "cairn" / "src" / "cairn" / "server" / "partials" / "view_settings.html").read_text(
            encoding="utf-8"
        )
        ui = (_REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "workspace" / "state-ui.js").read_text(
            encoding="utf-8"
        )
        settings = (_REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "app" / "state-settings.js").read_text(
            encoding="utf-8"
        )
        settings_admin = (
            _REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "app" / "state-settings-admin.js"
        ).read_text(encoding="utf-8")
        prompts = (_REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "app" / "state-prompts.js").read_text(
            encoding="utf-8"
        )
        capabilities = (
            _REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "workspace" / "state-capabilities.js"
        ).read_text(encoding="utf-8")

        self.assertNotIn("async navigateSettings(section = 'server')", ui)
        self.assertIn("section: 'prompts'", settings)
        self.assertIn("adminNavItems()", settings)
        self.assertIn("async navigateSettings(section = 'system')", settings)
        self.assertIn("async loadSettingsSection(section = this.settingsSection)", settings)
        self.assertIn("async loadSettings()", settings)
        self.assertIn("async saveServerSettings()", settings)
        self.assertIn("async loadSystemSettings()", settings_admin)
        self.assertIn("async saveSystemSettings()", settings_admin)
        self.assertIn("async loadPrompts()", prompts)
        self.assertIn("async loadPromptGroup()", prompts)
        self.assertIn("/prompt-templates", prompts)
        self.assertIn("/capabilities/catalog", prompts)
        self.assertIn("/roles/admin/", prompts)
        self.assertIn("/prompt-settings", prompts)
        self.assertNotIn("/default-skills", prompts)
        self.assertIn("promptTemplateRoutePath(name)", prompts)
        self.assertIn("promptSelectedIsRole()", prompts)
        self.assertIn("promptRoleRequiredSkillIds", prompts)
        self.assertIn("settingsSection === 'prompts'", view)
        self.assertNotIn('data-testid="prompts-group"', view)
        self.assertIn('data-testid="prompts-editor"', view)
        self.assertIn('data-testid="prompts-save"', view)
        self.assertIn('data-testid="role-required-skills"', view)
        self.assertIn("Required Skills", view)
        self.assertIn('x-show="promptSelectedIsRole()"', view)
        self.assertIn('x-model="promptRoleRequiredSkillIds"', view)
        self.assertIn("promptEditorResources()", prompts)
        self.assertIn("promptSelectedWritable()", prompts)
        self.assertNotIn("promptGroupSelected", prompts)
        self.assertNotIn("promptGroups", prompts)
        self.assertNotIn("deleteCapabilityAdmin", prompts)
        self.assertNotIn("/capabilities/admin/", prompts)
        self.assertNotIn("/prompt-groups", prompts)
        self.assertNotIn("promptTemplateNames: ['bootstrap.md'", prompts)
        self.assertNotIn("/prompt-groups", capabilities)
        self.assertNotIn("/role-prompts", capabilities)
        self.assertNotIn("/templates/", capabilities)
        self.assertNotIn("promptEditorResources()", capabilities)
        self.assertNotIn("promptSelectedWritable()", capabilities)

    def test_settings_prompt_editor_uses_available_viewport_height(self) -> None:
        view = (_REPO / "cairn" / "src" / "cairn" / "server" / "partials" / "view_settings.html").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'settingsSection === \'prompts\'" class="h-full min-h-0 flex flex-col',
            view,
        )
        self.assertIn("grid-cols-1 lg:grid-cols-[220px_minmax(0,1fr)] gap-3 flex-1 min-h-0", view)
        self.assertIn("min-h-0 flex-1 space-y-1 overflow-y-auto", view)
        self.assertIn("min-w-0 min-h-0 flex flex-col gap-2", view)
        self.assertIn("flex-1 min-h-[18rem] lg:min-h-0 overflow-y-auto resize-none", view)
        self.assertNotIn('settingsSection === \'prompts\'" class="min-h-[calc(100vh-13rem)]', view)
        self.assertNotIn("min-h-[520px]", view)

    def test_settings_capabilities_is_two_column_and_type_specific(self) -> None:
        view = (_REPO / "cairn" / "src" / "cairn" / "server" / "partials" / "view_settings.html").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'settingsSection === \'capabilities\'" class="h-full min-h-0 flex flex-col gap-3',
            view,
        )
        self.assertIn("data-testid=\"settings-capability-add-mcp\"", view)
        self.assertIn("data-testid=\"settings-capability-add-skill\"", view)
        self.assertIn("data-testid=\"settings-capability-probe-all-mcp\"", view)
        self.assertIn("Import MCP JSON", view)
        self.assertIn("Probe All", view)
        self.assertIn("MCP Servers", view)
        self.assertIn("Skills", view)
        self.assertIn("x-show=\"capabilityFormOpen\"", view)
        self.assertIn("x-show=\"!capabilityFormOpen && !capabilityImportOpen\"", view)
        self.assertIn("flex-1 min-h-0 overflow-y-auto", view)
        self.assertIn("flex-1 min-h-0 lg:grid-cols-2 lg:auto-rows-fr", view)
        self.assertIn('x-show="capabilityImportOpen" x-cloak class="flex-1 min-h-0 overflow-y-auto', view)
        self.assertNotIn('x-show="capabilityImportOpen && !capabilityFormOpen" x-cloak class="shrink-0', view)
        self.assertIn("h-32 overflow-hidden rounded-xl border border-slate-200 bg-white", view)
        self.assertNotIn("settingsSection === 'capabilities'\" class=\"flex min-h-[calc(100vh-13rem)]", view)
        self.assertNotIn("lg:min-h-[calc(100vh-14rem)]", view)
        self.assertIn("data-testid=\"prompts-reload\"", view)
        self.assertIn("data-testid=\"prompts-save\"", view)
        self.assertIn("flex items-center gap-2 shrink-0", view)
        self.assertIn(
            "h-7 inline-flex items-center justify-center px-3 text-xs rounded-lg border border-slate-200 text-slate-500",
            view,
        )
        self.assertIn(
            "h-7 inline-flex items-center justify-center px-3 text-xs rounded-lg bg-brand-500 text-white font-medium",
            view,
        )
        self.assertIn("No markdown prompt resources found.", view)
        self.assertNotIn("max-h-[calc(100vh-430px)]", view)
        self.assertNotIn("capabilityAdminPanel", view)
        self.assertIn('data-testid="capability-task-types"', view)
        self.assertIn("capabilityTaskTypes()", view)
        self.assertIn("capabilityTaskTypesSelected()", view)
        self.assertIn("capabilityTaskTypeSummary(item)", view)

    def test_settings_servers_and_proxy_match_ai_profile_management_layout(self) -> None:
        view = (_REPO / "cairn" / "src" / "cairn" / "server" / "partials" / "view_settings.html").read_text(
            encoding="utf-8"
        )
        servers_view = view.split("<section x-show=\"settingsSection === 'servers'\"", 1)[1].split(
            "<section x-show=\"settingsSection === 'proxy'\"",
            1,
        )[0]
        proxy_view = view.split("<section x-show=\"settingsSection === 'proxy'\"", 1)[1].split(
            "<section x-show=\"settingsSection === 'capabilities'\"",
            1,
        )[0]

        self.assertIn(
            'settingsSection === \'servers\'" class="h-full min-h-0 flex flex-col gap-3',
            view,
        )
        self.assertIn(
            'settingsSection === \'proxy\'" class="h-full min-h-0 flex flex-col gap-3',
            view,
        )
        self.assertNotIn("settingsSection === 'resources'", view)
        self.assertIn('data-testid="settings-server-refresh"', servers_view)
        self.assertIn('data-testid="settings-server-add"', servers_view)
        self.assertIn('x-show="!serverFormOpen"', servers_view)
        self.assertIn('x-show="serverFormOpen"', servers_view)
        self.assertIn('data-testid="server-save"', servers_view)
        self.assertNotIn('x-model="serverForm.auth_type"', servers_view)
        self.assertNotIn("<select x-model=\"serverForm.auth_type\"", servers_view)
        self.assertNotIn('x-model="serverForm.cert_path"', servers_view)
        self.assertIn('x-model="serverForm.password"', servers_view)
        self.assertIn('x-model="serverForm.private_key"', servers_view)
        self.assertIn('type="file"', servers_view)
        self.assertIn("serverForm.certificateFile", servers_view)
        self.assertIn("openEditServer(s)", servers_view)
        self.assertIn("deleteServerResource(s.id, s.name)", servers_view)
        self.assertIn("testServerResource(s.id)", servers_view)
        self.assertIn("Servers", servers_view)

        self.assertIn('data-testid="settings-proxy-refresh"', proxy_view)
        self.assertIn('data-testid="settings-proxy-back"', proxy_view)
        self.assertIn('data-testid="settings-proxy-add"', proxy_view)
        self.assertIn('data-testid="proxy-save"', proxy_view)
        self.assertIn("filteredProxyProjects()", proxy_view)
        self.assertIn("selectProxyProject(p)", proxy_view)
        self.assertIn("backToProxyProjects()", proxy_view)
        self.assertIn("proxySelectedProjectId && projectProxyFormOpen", proxy_view)
        self.assertIn("proxySelectedProjectId && !projectProxyFormOpen", proxy_view)
        self.assertIn("openEditProjectProxy(p)", proxy_view)
        self.assertIn("deleteProjectProxy(p.id, p.name)", proxy_view)
        self.assertIn("resolveProjectProxyChain(p.id)", proxy_view)
        self.assertNotIn("selectedProjectId", proxy_view)
        self.assertNotIn("openEditProxy(p.id)", proxy_view)

    def test_settings_primary_save_buttons_are_in_headers(self) -> None:
        view = (_REPO / "cairn" / "src" / "cairn" / "server" / "partials" / "view_settings.html").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("flex justify-end gap-2 mt-5", view)
        self.assertIn('data-testid="system-settings-save"', view)
        self.assertNotIn('data-testid="server-settings-save"', view)
        self.assertNotIn('data-testid="runtime-limits-save"', view)
        self.assertNotIn('data-testid="task-timeouts-save"', view)
        self.assertNotIn('data-testid="observability-save"', view)
        self.assertNotIn('data-testid="log-retention-save"', view)
        self.assertIn("shrink-0 space-y-1.5", view)
        self.assertIn(
            '<div class="text-[11px] text-slate-400">Identity, routing metadata, and type-specific settings are grouped below.</div>',
            view,
        )
        self.assertIn(
            '<div x-show="!capabilityFormOpen && !capabilityImportOpen" x-cloak class="flex flex-wrap items-center justify-end gap-2">',
            view,
        )
        self.assertIn(
            '<button data-testid="settings-capability-import" @click="openImportMcpJson()" class="h-7 inline-flex items-center justify-center px-3 text-xs rounded-lg border border-slate-200 text-slate-500',
            view,
        )
        self.assertIn(
            '<div x-show="capabilityImportOpen" x-cloak class="flex items-center gap-2">\n'
            '            <button @click="cancelImportMcpJson()" class="h-7 inline-flex items-center justify-center px-3 text-xs rounded-lg text-slate-500',
            view,
        )
        self.assertIn(
            'data-testid="capability-import-save" @click="importMcpJson()" class="h-7 inline-flex items-center justify-center px-3 text-xs rounded-lg bg-brand-500 text-white font-medium',
            view,
        )
        self.assertIn(
            '<div x-show="capabilityFormOpen" x-cloak class="flex items-center gap-3">\n'
            '            <label class="inline-flex items-center gap-2 text-[11px] text-slate-500">\n'
            '              <input type="checkbox" class="h-3.5 w-3.5 rounded border-slate-300 text-slate-700 focus:ring-brand-100" x-model="capabilityForm.available">\n'
            '              available\n'
            '            </label>\n'
            '            <div class="flex items-center gap-2">\n'
            '              <button @click="cancelCapabilityEdit()" class="h-7 inline-flex items-center justify-center',
            view,
        )
        self.assertIn(
            'data-testid="capability-save" @click="saveCapability()" :disabled="!capabilityForm.id.trim() || !capabilityForm.name.trim() || !capabilityTaskTypesSelected()" class="h-7 inline-flex items-center justify-center px-3 text-xs rounded-lg bg-brand-500 text-white font-medium',
            view,
        )
        self.assertNotIn(
            '              <div class="flex items-center gap-3">\n'
            '                <label class="inline-flex items-center gap-2 text-[11px] text-slate-500">',
            view,
        )


if __name__ == "__main__":
    unittest.main()
