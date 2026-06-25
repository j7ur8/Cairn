from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")

from helpers import reset_postgres_db


def _frontend_source() -> str:
    """The full shipped frontend surface as one searchable string.

    The SPA was split out of a single index.html into partials/*.html (markup,
    assembled by assemble_index()) and static/js/*.js (the Alpine app now
    assembled from native ES modules). Behavioral assertions below grep this
    combined surface, exactly as they used to grep the monolithic index.html.
    """
    from cairn.server.app import STATIC_DIR, assemble_index

    html = assemble_index()
    js = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted((STATIC_DIR / "js").rglob("*.js"))
    )
    return html + "\n" + js



class StaticCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_postgres_db()

    def tearDown(self) -> None:
        from cairn.server import db
        db.reset_for_tests()

    def test_static_assets_are_no_store(self) -> None:
        from fastapi.testclient import TestClient

        from cairn.server.app import app

        with TestClient(app) as client:
            r = client.get("/static/favicon.svg")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("cache-control"), "no-store, must-revalidate")

    def test_project_file_download_uses_authenticated_fetch(self) -> None:
        html = _frontend_source()
        self.assertIn("downloadProjectFile(file)", html)
        self.assertIn("async downloadProjectFile(file)", html)
        self.assertNotIn(':href="projectFileDownloadUrl(file)"', html)

    def test_text_export_uses_authenticated_fetch(self) -> None:
        html = _frontend_source()
        self.assertIn("async fetchText(path)", html)
        self.assertIn("await this.authFetch(path, { method: 'GET' })", html)
        self.assertNotIn("const r = await fetch(path);", html)

    def test_attachment_upload_uses_authenticated_fetch(self) -> None:
        html = _frontend_source()
        self.assertIn("async uploadProjectAttachments(projectId, attachments, actor)", html)
        self.assertIn(
            "await this.authFetch(`/projects/${encodeURIComponent(projectId)}/attachments`, { method: 'POST', body: form })",
            html,
        )

    def test_capabilities_save_uses_per_task_payload_once(self) -> None:
        html = _frontend_source()
        self.assertEqual(html.count("async saveCapabilities()"), 1)
        self.assertIn("const body = { capabilities: this.selectedCapabilitiesForPayload(this.capabilities.tasks) };", html)
        self.assertIn("tasks: this.taskCapabilitiesFromServerTasks(data.tasks)", html)
        self.assertNotIn("capabilities_per_task", html)
        self.assertNotIn("ai_profile_selections", html)

    def test_project_capability_picker_hides_role_default_top_level_skills(self) -> None:
        html = _frontend_source()
        self.assertIn("roleDefaultTopLevelSkillIds()", html)
        self.assertIn("return ['ctf-web-js-analysis'];", html)
        self.assertIn("selectableCapabilitiesForTask(task, items)", html)
        self.assertIn("sanitizeUserSkillIdsForProjectPayload(ids)", html)
        self.assertIn("selectableCapabilitiesForTask(task.key, newProjectCatalog.capabilities).filter(i => i.kind === 'skill')", html)
        self.assertIn("selectableCapabilitiesForTask(task.key, replayConfig.catalog?.capabilities || []).filter(i => i.kind === 'skill')", html)
        self.assertIn("skill_ids: this.sanitizeUserSkillIdsForProjectPayload(entry.user_skill_ids || []),", html)

    def test_llm_event_queries_use_visible_event_kind_allowlist(self) -> None:
        html = _frontend_source()
        self.assertIn("currentLlmVisibleEventKinds()", html)
        self.assertIn("params.append('event_kinds', kind);", html)
        self.assertIn("/llm-events/view?", html)
        self.assertIn("/llm-events/incremental?", html)
        self.assertIn("/llm-events/cards?", html)
        self.assertNotIn("include_low_signal", html)

    def test_execution_log_latest_preview_has_no_title_or_empty_copy(self) -> None:
        html = _frontend_source()
        self.assertNotIn(">Latest<", html)
        self.assertNotIn(">No recent events<", html)
        self.assertNotIn("x-show=\"llmLatestLoading\">Loading</span>", html)

    def test_execution_log_latest_preview_uses_visible_event_kind_allowlist(self) -> None:
        html = _frontend_source()
        latest_start = html.index("async loadLatestLlmEvents()")
        latest_end = html.index("estimateLlmPageSize()", latest_start)
        latest_source = html[latest_start:latest_end]
        self.assertIn("this.llmEventViewUrl({", latest_source)
        self.assertIn("limit: this.llmLatestEventLimit,", latest_source)
        self.assertNotIn("includeEventKinds: false", latest_source)

    def test_execution_log_uses_page_tokens_for_cards_pagination(self) -> None:
        html = _frontend_source()
        self.assertIn("llmEventCardsUrl({ executionId = '', pageSize = this.llmPageSize, pageToken = '' } = {})", html)
        self.assertIn("params.set('page_size', String(pageSize));", html)
        self.assertIn("params.set('page_token', pageToken);", html)
        self.assertIn("llmPageTokenHistory = [...this.llmPageTokenHistory, this.llmPageToken];", html)
        self.assertIn("const previousPageToken = stack.pop() || '';", html)
        self.assertNotIn("llmPageBackStack", html)

    def test_execution_log_all_selection_uses_sentinel(self) -> None:
        html = _frontend_source()
        self.assertIn("const ALL_LLM_EXECUTIONS_VALUE = '__all__';", html)
        self.assertIn("<option :value=\"ALL_LLM_EXECUTIONS_VALUE\">All executions</option>", html)
        self.assertIn("selectedLlmExecutionIdForQuery()", html)
        self.assertIn("return this.isAllLlmExecutionsSelected() ? '' : this.llmSelectedExecutionId;", html)
        self.assertNotIn("const running = next.find(execution => execution.process_state === 'running');", html)

    def test_execution_log_refresh_and_intent_selection_are_wired(self) -> None:
        html = _frontend_source()
        self.assertIn('title="Refresh Execution Log"', html)
        self.assertIn('@click="refreshCurrentLlmLog()"', html)
        self.assertIn("async refreshCurrentLlmLog()", html)
        self.assertIn("syncLlmExecutionSelectionForIntent(intentId)", html)
        self.assertIn("this.syncLlmExecutionSelectionForIntent?.(intentId);", html)

    def test_project_graph_uses_cytoscape_dagre_surface(self) -> None:
        html = _frontend_source()
        self.assertIn('id="cy"', html)
        self.assertIn('/static/vendor/dagre.min.js', html)
        self.assertIn('/static/vendor/cytoscape.min.js', html)
        self.assertIn('/static/vendor/cytoscape-dagre.js', html)
        self.assertIn("layoutMode: 'dagre_tb'", html)
        self.assertIn('value="dagre_tb"', html)
        self.assertIn('value="klay_tb"', html)
        self.assertIn('value="elk_tb"', html)
        self.assertIn("buildElements()", html)
        self.assertIn("layoutOpts()", html)
        self.assertIn("await this.api('GET', `/projects/${this.selectedProjectId}/poll-state`)", html)
        self.assertIn("cytoscape({", html)
        self.assertIn("rawCy.on('tap', 'node'", html)
        self.assertIn("rawCy.on('tap', 'edge'", html)
        self.assertIn("this.applyProjectPollState(pollState);", html)
        self.assertNotIn("projectGraphDataSignature(", html)
        self.assertNotIn("projectTimelineDataSignature(", html)
        self.assertNotIn("pulseActive()", html)
        self.assertNotIn("fadeInFreshElement(", html)
        self.assertNotIn("this.cy.animation({ center: { eles }", html)
        self.assertNotIn("selector: '.fresh'", html)
        self.assertNotIn('id="dagViewport"', html)
        self.assertNotIn('flowDagViewModel()', html)
        self.assertNotIn('class="dag-edges"', html)
        self.assertNotIn('x-ref="dagEdgesSvg"', html)
        self.assertNotIn('<template x-for="edge in flowDagViewModel().edges"', html)
        self.assertNotIn('<template x-for="junction in flowDagViewModel().junctions"', html)

    def test_detail_and_timeline_cards_render_full_text_without_summary_headline(self) -> None:
        html = _frontend_source()
        self.assertIn('x-text="fact.description"', html)
        self.assertIn('x-text="selectedFactRecord().description"', html)
        self.assertIn('x-text="selectedIntentRecord().description"', html)
        self.assertIn('x-text="entry.summary"', html)
        self.assertNotIn("summaryCardViewModel(fact.description, 'fact').headline", html)
        self.assertNotIn("summaryCardViewModel(selectedFactRecord().description, 'fact').headline", html)
        self.assertNotIn("summaryCardViewModel(selectedIntentRecord().description, 'intent').headline", html)
        self.assertNotIn("summaryCardViewModel(entry.summary, timelineSummaryKind(entry)).headline", html)

    def test_capability_admin_save_builds_kind_specific_payload(self) -> None:
        html = _frontend_source()
        self.assertIn("const normalizeStringList = (value) => {", html)
        self.assertIn("args: normalizeStringList(this.capabilityForm.args),", html)
        self.assertIn("payload.env = this.textToKeyValueObject(this.capabilityForm.env_text || '');", html)
        self.assertIn("required_skill_ids: normalizeStringList(this.capabilityForm.required_skill_ids),", html)
        self.assertIn("preferred_mcp_ids: normalizeStringList(this.capabilityForm.preferred_mcp_ids),", html)
        self.assertNotIn("const payload = { ...this.capabilityForm };", html)

    def test_capability_admin_ui_uses_two_columns_and_import_action(self) -> None:
        html = _frontend_source()
        self.assertIn("data-testid=\"settings-capability-add-mcp\"", html)
        self.assertIn("data-testid=\"settings-capability-add-skill\"", html)
        self.assertIn("data-testid=\"settings-capability-import\"", html)
        self.assertIn("data-testid=\"settings-capability-probe-all-mcp\"", html)
        self.assertIn("/capabilities/admin/mcp/probe-all", html)
        self.assertIn("/capabilities/admin/mcp_server/", html)
        self.assertIn("async importMcpJson()", html)
        self.assertIn("async probeAllMcpCapabilities()", html)
        self.assertIn("capabilityItems('mcp_server')", html)
        self.assertIn("capabilityItems('skill')", html)
        self.assertEqual(html.count('@click="deleteCapabilityAdmin(item.kind, item.id, item.name)"'), 2)
        self.assertNotIn('x-show="item.source === \'user\'"', html)
        self.assertNotIn("data-testid=\"settings-capability-add\"", html)

    def test_ai_profile_form_actions_live_in_header(self) -> None:
        html = _frontend_source()
        ai_start = html.index(
            '<section x-show="settingsSection === \'ai\'" class="h-full min-h-0 flex flex-col gap-3">'
        )
        ai_end = html.index("<!-- Prompts -->", ai_start)
        ai_section = html[ai_start:ai_end]
        form_start = ai_section.index(
            '<div x-show="aiProfileForm.id || aiProfileFormOpen" x-cloak class="flex-1 min-h-0 overflow-y-auto'
        )
        list_start = ai_section.index(
            '<template x-if="!aiProfileForm.id && !aiProfileFormOpen && aiProfiles.length === 0">',
            form_start,
        )
        ai_header = ai_section[:form_start]
        ai_form = ai_section[form_start:list_start]
        ai_list = ai_section[list_start:]

        self.assertIn('x-show="!aiProfileForm.id && !aiProfileFormOpen"', ai_header)
        self.assertIn('data-testid="settings-ai-refresh"', ai_header)
        self.assertIn('data-testid="settings-ai-add"', ai_header)
        self.assertIn('x-show="aiProfileForm.id || aiProfileFormOpen"', ai_header)
        self.assertIn('x-model="aiProfileForm.available"', ai_header)
        self.assertIn('@click="cancelAiProfileEdit()"', ai_header)
        self.assertIn('data-testid="ai-profile-save"', ai_header)
        self.assertIn(':disabled="!aiProfileForm.name.trim() || !aiProfileForm.model.trim()"', ai_header)
        self.assertIn('x-text="aiProfileForm.id ? \'Save\' : \'Create\'"', ai_header)
        self.assertIn(
            'class="h-7 inline-flex items-center justify-center px-3 text-xs rounded-lg text-slate-500 hover:bg-slate-50 transition"',
            ai_header,
        )
        self.assertIn(
            'class="h-7 inline-flex items-center justify-center px-3 text-xs rounded-lg bg-brand-500 text-white font-medium hover:bg-brand-600 transition disabled:opacity-30 disabled:cursor-not-allowed"',
            ai_header,
        )
        self.assertNotIn('@click="cancelAiProfileEdit()"', ai_form)
        self.assertNotIn('data-testid="ai-profile-save"', ai_form)
        self.assertNotIn('x-model="aiProfileForm.available"', ai_form)
        self.assertIn('x-show="!aiProfileForm.id && !aiProfileFormOpen"', ai_list)
        self.assertIn('class="space-y-2 flex-1 min-h-0 overflow-y-auto pr-1"', ai_list)
        self.assertNotIn(
            'class="px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-50 rounded-lg transition"',
            ai_section,
        )
        self.assertNotIn(
            'class="px-3 py-1.5 text-xs bg-brand-500 text-white rounded-lg font-medium hover:bg-brand-600 transition disabled:opacity-30 disabled:cursor-not-allowed"',
            ai_section,
        )

    def test_projects_view_uses_flex_height_chain_for_internal_scroll(self) -> None:
        shell = (
            _REPO / "cairn" / "src" / "cairn" / "server" / "partials" / "shell_content_open.html"
        ).read_text(encoding="utf-8")
        view = (
            _REPO / "cairn" / "src" / "cairn" / "server" / "partials" / "view_list.html"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '<main x-show="view !== \'newProject\'" x-cloak class="min-h-0 flex-1 flex flex-col overflow-hidden">',
            shell,
        )
        self.assertIn(
            '<div x-show="view === \'list\'" x-cloak class="flex-1 min-h-0 flex flex-col overflow-hidden">',
            view,
        )
        self.assertIn(
            'x-ref="projectListScroll" @scroll.passive="rememberProjectListScroll()" class="flex-1 min-h-0 h-full overflow-y-auto p-4"',
            view,
        )

    def test_cairn_app_uses_single_module_entrypoint(self) -> None:
        app_js = (_REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "app" / "index.js").read_text(
            encoding="utf-8"
        )
        doc_open = (_REPO / "cairn" / "src" / "cairn" / "server" / "partials" / "_doc_open.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('<script type="module" src="/static/js/app/index.js"></script>', doc_open)
        self.assertIn("createSettingsState()", app_js)
        self.assertIn("createSettingsAdminState()", app_js)
        self.assertIn("createPromptsState()", app_js)
        self.assertIn("createAiProfilesState()", app_js)
        self.assertIn("createProxiesState()", app_js)
        self.assertIn("createWorkspaceCapabilitiesState()", app_js)
        self.assertIn("window.cairnApp = function cairnApp()", app_js)
        self.assertIn("duplicate app state key overwritten", (_REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "app" / "create-app-state.js").read_text(encoding="utf-8"))

    def test_settings_navigation_uses_section_specific_loaders(self) -> None:
        settings = (_REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "app" / "state-settings.js").read_text(
            encoding="utf-8"
        )
        ui = (_REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "workspace" / "state-ui.js").read_text(
            encoding="utf-8"
        )
        core = (_REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "app" / "state-core.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("async navigateSettings(section = 'system')", settings)
        self.assertIn("await this.loadSettingsSection(section);", settings)
        self.assertIn("system: () => this.loadSystemSettings()", settings)
        self.assertIn("prompts: async () => {", settings)
        self.assertIn("ai: () => this.loadAiProfiles()", settings)
        self.assertIn("capabilities: () => this.loadCapabilityAdmin()", settings)
        self.assertIn("proxies: () => this.loadProxies()", settings)
        self.assertNotIn("server: () => this.loadSettings()", settings)
        self.assertNotIn("runtime: () => this.loadRuntimeLimits()", settings)
        self.assertNotIn("tasks: () => this.loadTaskTimeouts()", settings)
        self.assertNotIn("observability: () => this.loadObservability()", settings)
        self.assertNotIn("Promise.all([\n        this.loadSettings(),\n        this.loadAiProfiles(),", settings)
        self.assertNotIn("async navigateSettings(section = 'server')", ui)
        self.assertIn("await this.loadSettings();", core)
        self.assertNotIn("await this.loadRuntimeLimits();", core)
        self.assertNotIn("await this.loadCapabilityAdmin();", core)

    def test_capabilities_slice_excludes_non_capability_admin_endpoints(self) -> None:
        capabilities = (
            _REPO / "cairn" / "src" / "cairn" / "server" / "static" / "js" / "workspace" / "state-capabilities.js"
        ).read_text(encoding="utf-8")
        self.assertNotIn("/prompt-groups", capabilities)
        self.assertNotIn("/role-prompts", capabilities)
        self.assertNotIn("/ai-profiles", capabilities)
        self.assertNotIn("/proxies", capabilities)
        self.assertNotIn("/runtime-limits", capabilities)
        self.assertNotIn("/task-timeouts", capabilities)
        self.assertIn("/capabilities/admin", capabilities)
        self.assertIn("/projects/${this.selectedProjectId}/capabilities", capabilities)

    def test_health_reports_postgres_status(self) -> None:
        from fastapi.testclient import TestClient

        from cairn.server.app import app

        with TestClient(app) as client:
            r = client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")
        self.assertEqual(r.json()["database"], "postgresql")

    def test_health_reports_database_errors_as_degraded(self) -> None:
        from fastapi.testclient import TestClient

        from cairn.server.app import app

        with patch("cairn.server.app.db.postgres_status", side_effect=RuntimeError("postgres unavailable")), TestClient(app) as client:
            r = client.get("/health")
        self.assertEqual(r.status_code, 503)
        body = r.json()
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["database"], "postgresql")
        self.assertEqual(body["error"], "database_unavailable")
        self.assertIn("request_id", body)
        self.assertNotIn("postgres unavailable", json.dumps(body))

    def test_database_unavailable_handler_returns_degraded_json(self) -> None:
        import asyncio

        from cairn.server.app import database_unavailable_handler
        from cairn.server.db import DatabaseUnavailable

        r = asyncio.run(database_unavailable_handler(None, DatabaseUnavailable("postgres unavailable")))
        self.assertEqual(r.status_code, 503)
        body = json.loads(r.body)
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["database"], "postgresql")
        self.assertEqual(body["error"], "database_unavailable")
        self.assertIn("request_id", body)
        self.assertNotIn("postgres unavailable", json.dumps(body))


if __name__ == "__main__":
    unittest.main()
