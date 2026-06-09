from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class StaticCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from cairn.server import db
        from cairn.server.observability import db as obs_db
        db.reset_for_tests()
        db.close_thread_conn()
        db.configure(Path(self.tmp.name) / "main.sqlite")
        obs_db.configure(Path(self.tmp.name) / "obs.sqlite")

    def tearDown(self) -> None:
        from cairn.server import db
        db.close_thread_conn()
        db.reset_for_tests()
        self.tmp.cleanup()

    def test_static_assets_are_no_store(self) -> None:
        from fastapi.testclient import TestClient
        from cairn.server.app import app

        with TestClient(app) as client:
            r = client.get("/static/favicon.svg")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("cache-control"), "no-store, must-revalidate")

    def test_project_file_download_uses_authenticated_fetch(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "src" / "cairn" / "server" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("downloadProjectFile(file)", html)
        self.assertIn("async downloadProjectFile(file)", html)
        self.assertNotIn(':href="projectFileDownloadUrl(file)"', html)

    def test_text_export_uses_authenticated_fetch(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "src" / "cairn" / "server" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("async fetchText(path)", html)
        self.assertIn("await this.authFetch(path, { method: 'GET' })", html)
        self.assertNotIn("const r = await fetch(path);", html)

    def test_attachment_upload_uses_authenticated_fetch(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "src" / "cairn" / "server" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("async uploadProjectAttachments(projectId, attachments, actor)", html)
        self.assertIn(
            "await this.authFetch(`/projects/${encodeURIComponent(projectId)}/attachments`, { method: 'POST', body: form })",
            html,
        )

    def test_capabilities_save_uses_per_task_payload_once(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "src" / "cairn" / "server" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertEqual(html.count("async saveCapabilities()"), 1)
        self.assertIn("const body = { capabilities: this.selectedCapabilitiesForPayload(this.capabilities.tasks) };", html)
        self.assertIn("tasks: this.taskCapabilitiesFromServerTasks(data.tasks)", html)
        self.assertNotIn("capabilities_per_task", html)
        self.assertNotIn("ai_profile_selections", html)

    def test_project_capability_picker_hides_role_default_top_level_skills(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "src" / "cairn" / "server" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("roleDefaultTopLevelSkillIds()", html)
        self.assertIn("return ['cypher-ctf', 'cypher-pentest', 'cypher-vuln-research'];", html)
        self.assertIn("selectableCapabilitiesForTask(task, items)", html)
        self.assertIn("sanitizeUserSkillIdsForProjectPayload(ids)", html)
        self.assertIn("selectableCapabilitiesForTask(task.key, newProjectCatalog.capabilities).filter(i => i.kind === 'skill')", html)
        self.assertIn("selectableCapabilitiesForTask(task.key, replayConfig.catalog?.capabilities || []).filter(i => i.kind === 'skill')", html)
        self.assertIn("skill_ids: this.sanitizeUserSkillIdsForProjectPayload(entry.user_skill_ids || []),", html)

    def test_capability_admin_save_builds_kind_specific_payload(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "src" / "cairn" / "server" / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("const normalizeStringList = (value) => {", html)
        self.assertIn("args: normalizeStringList(this.capabilityForm.args),", html)
        self.assertIn("required_skill_ids: normalizeStringList(this.capabilityForm.required_skill_ids),", html)
        self.assertIn("preferred_mcp_ids: normalizeStringList(this.capabilityForm.preferred_mcp_ids),", html)
        self.assertNotIn("const payload = { ...this.capabilityForm };", html)

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
        self.assertIn("postgres unavailable", body["database_error"])

    def test_route_database_errors_are_degraded_json(self) -> None:
        from fastapi.testclient import TestClient
        from cairn.server.db import DatabaseUnavailable
        from cairn.server.app import app
        from cairn.server.security.jwt import issue_token

        @contextmanager
        def broken_get_conn():
            raise DatabaseUnavailable("postgres unavailable")
            yield

        headers = {
            "Authorization": f"Bearer {issue_token('test-service', extra_claims={'role': 'service'})}",
        }
        with patch("cairn.server.routers.settings.get_conn", broken_get_conn), TestClient(app) as client:
            r = client.get("/settings", headers=headers)
        self.assertEqual(r.status_code, 503)
        body = r.json()
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["database"], "postgresql")
        self.assertIn("postgres unavailable", body["database_error"])


if __name__ == "__main__":
    unittest.main()
