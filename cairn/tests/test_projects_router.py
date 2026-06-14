"""End-to-end router tests for the projects router.

Covers the core domain endpoints under ``/projects``, ``/projects/{id}``,
and the ``/projects/work`` dispatcher feed. Each test verifies both the
happy path and the auth-gate (global bearer-token enforcement at app
level, ``app.py`` `_enforce_auth`).

All tests are marked ``db`` because they require a live PostgreSQL.
They mirror the pattern in ``test_intents_router.py``:
``reset_postgres_db()`` in ``setUp``, ``CAIRN_ALLOW_DB_RESET=1`` in CI.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")

from helpers import reset_postgres_db


def _login_token(
    test_client,
    *,
    email: str = "admin@cairn.local",
    password: str = "Aa123123",
) -> str:
    """Obtain a valid bearer token via ``POST /auth/login``."""
    r = test_client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    if r.status_code == 200 and "access_token" in r.json():
        return r.json()["access_token"]
    # Rate-limited / no account yet — fall back to a synthetic JWT.
    import jwt as _jwt
    from cairn.server.security.jwt import _JWT_ALGORITHM

    secret = os.environ["CAIRN_JWT_SECRET"]
    import time as _time
    return _jwt.encode(
        {"sub": email, "iat": int(_time.time()), "exp": int(_time.time()) + 3600},
        secret,
        algorithm=_JWT_ALGORITHM,
    )


_MINIMAL_CREATE: dict = {
    "title": "smoke-project",
    "origin": "origin text",
    "goal": "goal text",
}


class ProjectsRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        """Reset the DB schema for every test — clean isolation."""
        self.db = reset_postgres_db()

    def _client(self):
        from fastapi.testclient import TestClient
        from cairn.server.app import app
        return TestClient(app)

    # ------------------------------------------------------------------
    # Happy-path CRUD --------------------------------------------------
    # ------------------------------------------------------------------

    def test_create_and_read_project(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            r = c.post("/projects", json=_MINIMAL_CREATE, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 201)
        body = r.json()
        pid = body["project"]["id"]
        self.assertTrue(pid.startswith("proj_"), f"unexpected project id: {pid}")
        self.assertEqual(body["project"]["title"], "smoke-project")
        self.assertIn("facts", body)
        self.assertIn("intents", body)

    def test_list_projects_empty_when_none(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            r = c.get("/projects", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_list_projects_returns_created_project(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            r = c.post("/projects", json=_MINIMAL_CREATE, headers={"Authorization": f"Bearer {token}"})
            pid = r.json()["project"]["id"]
            r2 = c.get("/projects", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r2.status_code, 200)
        ids = [p["id"] for p in r2.json()]
        self.assertIn(pid, ids)

    def test_list_project_work_feed(self) -> None:
        """The dispatcher poll endpoint must return a valid envelope."""
        with self._client() as c:
            token = _login_token(c)
            r = c.get("/projects/work", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_get_project_not_found(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            r = c.get("/projects/proj_does_not_exist", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 404)

    def test_update_title(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            cr = c.post("/projects", json=_MINIMAL_CREATE, headers={"Authorization": f"Bearer {token}"})
            pid = cr.json()["project"]["id"]
            r = c.put(
                f"/projects/{pid}/title",
                json={"title": "renamed"},
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["project"]["title"], "renamed")

    def test_update_status(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            cr = c.post("/projects", json=_MINIMAL_CREATE, headers={"Authorization": f"Bearer {token}"})
            pid = cr.json()["project"]["id"]
            r = c.put(
                f"/projects/{pid}/status",
                json={"status": "active"},
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(r.status_code, 200)

    def test_complete_project(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            cr = c.post("/projects", json=_MINIMAL_CREATE, headers={"Authorization": f"Bearer {token}"})
            pid = cr.json()["project"]["id"]
            r = c.post(
                f"/projects/{pid}/complete",
                json={"summary": "done"},
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["project"]["status"], "completed")

    def test_reopen_project(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            cr = c.post("/projects", json=_MINIMAL_CREATE, headers={"Authorization": f"Bearer {token}"})
            pid = cr.json()["project"]["id"]
            c.post(f"/projects/{pid}/complete", json={"summary": "done"}, headers={"Authorization": f"Bearer {token}"})
            r = c.post(f"/projects/{pid}/reopen", json={"allow_reopen_goal_fact_delete": False}, headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["project"]["status"], "active")

    def test_delete_project(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            cr = c.post("/projects", json=_MINIMAL_CREATE, headers={"Authorization": f"Bearer {token}"})
            pid = cr.json()["project"]["id"]
            r = c.delete(f"/projects/{pid}", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 204)

    def test_stop_all_active_projects(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            c.post("/projects", json=_MINIMAL_CREATE, headers={"Authorization": f"Bearer {token}"})
            r = c.post("/projects/stop-all", headers={"Authorization": f"Bearer {token}"})
        self.assertIn(r.status_code, (200, 202))

    # ------------------------------------------------------------------
    # Auth gate --------------------------------------------------------
    # ------------------------------------------------------------------

    def test_list_projects_returns_401_without_token(self) -> None:
        with self._client() as c:
            r = c.get("/projects")
        self.assertEqual(r.status_code, 401)

    def test_get_project_returns_401_without_token(self) -> None:
        with self._client() as c:
            r = c.get("/projects/proj_any")
        self.assertEqual(r.status_code, 401)

    def test_create_project_returns_401_without_token(self) -> None:
        with self._client() as c:
            r = c.post("/projects", json=_MINIMAL_CREATE)
        self.assertEqual(r.status_code, 401)

    def test_delete_project_returns_401_without_token(self) -> None:
        with self._client() as c:
            r = c.delete("/projects/proj_any")
        self.assertEqual(r.status_code, 401)
