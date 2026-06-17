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

    def test_list_prompt_groups(self) -> None:
        result = self.router.list_prompt_groups()

        self.assertEqual(result["groups"], ["custom", "default"])

    def test_read_prompt_group_returns_templates_and_hashes(self) -> None:
        roles_dir = self.root / "default" / "roles"
        roles_dir.mkdir()
        (roles_dir / "redteam.md").write_text("extra role prompt\n", encoding="utf-8")

        result = self.router.read_prompt_group("default")

        self.assertEqual(result["prompt_group"], "default")
        self.assertEqual(
            set(result["prompts"]),
            {
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

    def test_read_role_prompts_returns_markdown_files_and_hashes(self) -> None:
        role_root = self.root / "capabilities" / "roles"
        (role_root / "cypher-ctf-operator").mkdir(parents=True)
        (role_root / "cypher-ctf-operator" / "ROLE.md").write_text("ctf role\n", encoding="utf-8")
        (role_root / "cypher-pentest-operator").mkdir(parents=True)
        (role_root / "cypher-pentest-operator" / "ROLE.md").write_text("pentest role\n", encoding="utf-8")

        result = self.router.read_role_prompts()

        self.assertEqual(result["role_names"], ["cypher-ctf-operator/ROLE.md", "cypher-pentest-operator/ROLE.md"])
        self.assertEqual(result["roles"]["cypher-ctf-operator/ROLE.md"], "ctf role\n")
        self.assertRegex(result["role_sha256"]["cypher-ctf-operator/ROLE.md"], r"^[0-9a-f]{64}$")

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

    def test_update_prompt_template_writes_file_and_updates_hash(self) -> None:
        from cairn.shared.config.constants import DEFAULT_PROMPT_REQUIRED_TOKENS

        before = self.router.read_prompt_group("default")
        content = "updated reason\n" + " ".join(DEFAULT_PROMPT_REQUIRED_TOKENS["reason.md"]) + "\n"
        body = self.router.PromptGroupTemplateUpdate(content=content)
        after = self.router.update_prompt_template_legacy("default", "reason.md", body)

        self.assertEqual((self.root / "default" / "reason.md").read_text(encoding="utf-8"), content)
        self.assertEqual(after["prompts"]["reason.md"], content)
        self.assertNotEqual(before["prompt_sha256"]["reason.md"], after["prompt_sha256"]["reason.md"])
        self.assertNotEqual(before["prompts_sha256"], after["prompts_sha256"])

    def test_update_nested_prompt_template_writes_file_and_updates_hash(self) -> None:
        roles_dir = self.root / "default" / "roles"
        roles_dir.mkdir()
        (roles_dir / "redteam.md").write_text("original role prompt\n", encoding="utf-8")

        before = self.router.read_prompt_group("default")
        content = "updated role prompt\n"
        body = self.router.PromptGroupTemplateUpdate(content=content)
        after = self.router.update_prompt_template("default", "roles/redteam.md", body)

        self.assertEqual((roles_dir / "redteam.md").read_text(encoding="utf-8"), content)
        self.assertEqual(after["prompts"]["roles/redteam.md"], content)
        self.assertNotEqual(before["prompt_sha256"]["roles/redteam.md"], after["prompt_sha256"]["roles/redteam.md"])
        self.assertNotEqual(before["prompts_sha256"], after["prompts_sha256"])

    def test_extra_prompt_template_does_not_require_core_placeholders(self) -> None:
        roles_dir = self.root / "default" / "roles"
        roles_dir.mkdir()
        (roles_dir / "redteam.md").write_text("original role prompt\n", encoding="utf-8")
        body = self.router.PromptGroupTemplateUpdate(content="no placeholders required here\n")

        after = self.router.update_prompt_template("default", "roles/redteam.md", body)

        self.assertEqual(after["prompts"]["roles/redteam.md"], "no placeholders required here\n")

    def test_update_missing_required_placeholder_fails_without_writing(self) -> None:
        from fastapi import HTTPException

        original = (self.root / "default" / "reason.md").read_text(encoding="utf-8")
        body = self.router.PromptGroupTemplateUpdate(content="{graph_yaml}\n")

        with self.assertRaises(HTTPException) as cm:
            self.router.update_prompt_template_legacy("default", "reason.md", body)

        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("missing placeholders", cm.exception.detail)
        self.assertEqual((self.root / "default" / "reason.md").read_text(encoding="utf-8"), original)

    def test_invalid_group_name_and_template_name_are_rejected(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as group_cm:
            self.router.read_prompt_group("../default")
        with self.assertRaises(HTTPException) as name_cm:
            self.router.update_prompt_template_legacy(
                "default",
                "../reason.md",
                self.router.PromptGroupTemplateUpdate(content="x"),
            )

        self.assertEqual(group_cm.exception.status_code, 404)
        self.assertEqual(name_cm.exception.status_code, 400)

    def test_nested_template_invalid_paths_are_rejected(self) -> None:
        from fastapi import HTTPException

        for name in ("../x.md", "/x.md", "roles\\x.md", "roles/x.txt"):
            with self.subTest(name=name):
                with self.assertRaises(HTTPException) as cm:
                    self.router.update_prompt_template(
                        "default",
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
    def test_settings_contains_prompt_editor_controls(self) -> None:
        view = (_REPO / "cairn" / "src" / "cairn" / "server" / "partials" / "view_settings.html").read_text(
            encoding="utf-8"
        )
        ui = (_REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "parts.ui.js").read_text(
            encoding="utf-8"
        )
        settings = (_REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "parts.settings.js").read_text(
            encoding="utf-8"
        )
        settings_admin = (
            _REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "parts.settings_admin.js"
        ).read_text(encoding="utf-8")
        prompts = (_REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "parts.prompts.js").read_text(
            encoding="utf-8"
        )
        capabilities = (
            _REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "parts.capabilities.js"
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
        self.assertIn("async loadPromptGroups()", prompts)
        self.assertIn("async loadPromptGroup(group = this.promptGroupSelected)", prompts)
        self.assertIn("promptTemplateRoutePath(name)", prompts)
        self.assertIn("settingsSection === 'prompts'", view)
        self.assertIn('data-testid="prompts-group"', view)
        self.assertIn('data-testid="prompts-editor"', view)
        self.assertIn('data-testid="prompts-save"', view)
        self.assertIn("promptEditorResources()", prompts)
        self.assertIn("promptSelectedWritable()", prompts)
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
        self.assertNotIn("capabilityTaskTypes()", view)

    def test_settings_proxies_matches_capabilities_management_layout(self) -> None:
        view = (_REPO / "cairn" / "src" / "cairn" / "server" / "partials" / "view_settings.html").read_text(
            encoding="utf-8"
        )
        proxy_view = view.split("<section x-show=\"settingsSection === 'proxies'\"", 1)[1].split(
            "<section x-show=\"settingsSection === 'capabilities'\"",
            1,
        )[0]

        self.assertIn(
            'settingsSection === \'proxies\'" class="h-full min-h-0 flex flex-col gap-3',
            view,
        )
        self.assertIn('data-testid="settings-proxy-add"', proxy_view)
        self.assertIn('data-testid="proxy-save"', proxy_view)
        self.assertIn('x-show="proxyForm.id || proxyFormOpen" x-cloak class="flex-1 min-h-0 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50/60 p-3"', proxy_view)
        self.assertIn('x-show="!proxyFormOpen && !proxyForm.id" x-cloak class="rounded-xl border border-slate-200 bg-slate-50/70 p-3 shadow-sm flex flex-1 min-h-0 flex-col"', proxy_view)
        self.assertIn("Identity", proxy_view)
        self.assertIn("Connection", proxy_view)
        self.assertIn("Authentication", proxy_view)
        self.assertIn("Proxy Pool", proxy_view)
        self.assertIn("h-32 overflow-hidden rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm", proxy_view)
        self.assertIn("h-full min-h-[14rem] rounded-lg border border-dashed border-slate-200 bg-white/90 px-4 py-6 flex items-center justify-center text-center", proxy_view)
        self.assertIn("openEditProxy(p.id)", proxy_view)
        self.assertIn("deleteProxy(p.id, p.name)", proxy_view)
        self.assertNotIn("max-h-[calc(100vh-260px)]", proxy_view)

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
            'data-testid="capability-save" @click="saveCapability()" :disabled="!capabilityForm.id.trim() || !capabilityForm.name.trim()" class="h-7 inline-flex items-center justify-center px-3 text-xs rounded-lg bg-brand-500 text-white font-medium',
            view,
        )
        self.assertNotIn(
            '              <div class="flex items-center gap-3">\n'
            '                <label class="inline-flex items-center gap-2 text-[11px] text-slate-500">',
            view,
        )


if __name__ == "__main__":
    unittest.main()
