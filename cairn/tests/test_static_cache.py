from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class StaticCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from cairn.server import db
        from cairn.server.observability import db as obs_db
        db._db_path = None
        db.close_thread_conn()
        db.configure(Path(self.tmp.name) / "main.sqlite")
        obs_db._db_path = None
        obs_db.configure(Path(self.tmp.name) / "obs.sqlite")

    def tearDown(self) -> None:
        from cairn.server import db
        from cairn.server.observability import db as obs_db
        db.close_thread_conn()
        db._db_path = None
        obs_db._db_path = None
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

    def test_health_reports_migration_errors(self) -> None:
        from fastapi.testclient import TestClient
        from cairn.server import db
        from cairn.server.app import app

        with db.with_immediate_tx() as conn:
            conn.execute(
                "INSERT INTO migration_errors (version, sql, error) VALUES (?, ?, ?)",
                ("v_bad", "SELECT bad", "boom"),
            )
        with TestClient(app) as client:
            r = client.get("/health")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["status"], "degraded")
        self.assertEqual(r.json()["migration_error"]["version"], "v_bad")


if __name__ == "__main__":
    unittest.main()
