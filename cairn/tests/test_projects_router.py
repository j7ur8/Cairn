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
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text

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


def _complete_create_payload(profile_id: str) -> dict:
    selection = {
        "primary_profile_id": profile_id,
        "primary_model": "gpt-test",
        "primary_reasoning_type": "medium",
        "fallback_profile_ids": [],
    }
    return {
        **_MINIMAL_CREATE,
        "task_timeouts": {
            "bootstrap": {"timeout": 5, "conclude_timeout": 5},
            "explore": {"timeout": 5, "conclude_timeout": 5},
            "reason": {"timeout": 5, "max_intents": 2},
        },
        "ai_profiles": {
            "bootstrap": selection,
            "explore": selection,
            "reason": selection,
        },
    }


class ProjectsRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        """Reset the DB schema for every test — clean isolation."""
        self.db = reset_postgres_db()

    def _client(self):
        from fastapi.testclient import TestClient

        from cairn.server.app import app
        return TestClient(app)

    def _create_ai_profile_id(self, client, token: str) -> str:
        response = client.post(
            "/ai-profiles",
            json={
                "name": "test-profile",
                "worker_type": "codex",
                "model": "gpt-test",
                "api_key_env": "OPENAI_API_KEY",
                "sk": "test-key",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

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

    def test_create_project_clears_reused_storage_dirs(self) -> None:
        from cairn.server import runtime_config

        old_project_root = runtime_config.system_config().paths.resolved_project_files_root
        old_attachments_root = runtime_config.system_config().paths.resolved_attachments_root
        with tempfile.TemporaryDirectory() as td:
            project_root = Path(td) / "project-files"
            attachments_root = Path(td) / "attachments"
            runtime_config.system_config().paths.project_files_root = str(project_root)
            runtime_config.system_config().paths.attachments_root = str(attachments_root)
            try:
                (project_root / "proj_001" / "reports").mkdir(parents=True)
                (project_root / "proj_001" / "reports" / "stale.md").write_text("old", encoding="utf-8")
                (attachments_root / "proj_001").mkdir(parents=True)
                (attachments_root / "proj_001" / "stale.zip").write_text("old", encoding="utf-8")

                with self._client() as c:
                    token = _login_token(c)
                    profile_id = self._create_ai_profile_id(c, token)
                    created = c.post(
                        "/projects",
                        json=_complete_create_payload(profile_id),
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    pid = created.json()["project"]["id"]
                    files = c.get(f"/projects/{pid}/files", headers={"Authorization": f"Bearer {token}"})
            finally:
                runtime_config.system_config().paths.project_files_root = old_project_root
                runtime_config.system_config().paths.attachments_root = old_attachments_root

        self.assertEqual(created.status_code, 201)
        self.assertEqual(pid, "proj_001")
        self.assertEqual(files.status_code, 200)
        self.assertEqual(files.json()["files"], [])

    def test_create_project_storage_failure_rolls_back_database_row(self) -> None:
        from cairn.server import db
        from cairn.server.domain.errors import ServerInvariantError

        with self._client() as c:
            token = _login_token(c)
            profile_id = self._create_ai_profile_id(c, token)
            with patch(
                "cairn.server.application.project_creation.prepare_project_storage",
                side_effect=ServerInvariantError("storage unavailable"),
            ):
                r = c.post(
                    "/projects",
                    json=_complete_create_payload(profile_id),
                    headers={"Authorization": f"Bearer {token}"},
                )

        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.json()["detail"], "storage unavailable")
        with db.session_scope() as conn:
            rows = conn.execute(text("SELECT id FROM projects")).fetchall()
        self.assertEqual(rows, [])

    def test_list_projects_empty_when_none(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            r = c.get("/projects", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_project_cursor_round_trip_is_stable(self) -> None:
        from cairn.server.application.project_queries import _decode_cursor, _encode_cursor

        row = {"created_at": "2026-06-06T00:00:00Z", "id": "proj_001"}
        self.assertEqual(_decode_cursor(_encode_cursor(row)), (row["created_at"], row["id"]))

    def test_list_projects_returns_created_project(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            r = c.post("/projects", json=_MINIMAL_CREATE, headers={"Authorization": f"Bearer {token}"})
            pid = r.json()["project"]["id"]
            r2 = c.get("/projects", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r2.status_code, 200)
        ids = [p["id"] for p in r2.json()]
        self.assertIn(pid, ids)

    def test_list_projects_supports_cursor_pagination(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            ids = []
            for idx in range(3):
                payload = {**_MINIMAL_CREATE, "title": f"project-{idx}"}
                created = c.post("/projects", json=payload, headers={"Authorization": f"Bearer {token}"})
                ids.append(created.json()["project"]["id"])
            first = c.get("/projects?limit=2", headers={"Authorization": f"Bearer {token}"}).json()
            second = c.get(f"/projects?limit=2&cursor={first['next_cursor']}", headers={"Authorization": f"Bearer {token}"}).json()
        seen = [item["id"] for item in first["items"] + second["items"]]
        self.assertEqual(len(seen), len(set(seen)))
        self.assertTrue(set(ids).issubset(set(seen)))

    def test_list_project_work_feed(self) -> None:
        """The dispatcher poll endpoint must return a valid envelope."""
        with self._client() as c:
            token = _login_token(c)
            r = c.get("/projects/work", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_list_project_work_supports_cursor_pagination(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            for idx in range(2):
                payload = {**_MINIMAL_CREATE, "title": f"work-{idx}"}
                c.post("/projects", json=payload, headers={"Authorization": f"Bearer {token}"})
            r = c.get("/projects/work?limit=1", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body["items"]), 1)
        self.assertIsNotNone(body["next_cursor"])

    def test_get_project_not_found(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            r = c.get("/projects/proj_does_not_exist", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 404)

    def test_get_project_poll_state_returns_lightweight_fields(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            created = c.post("/projects", json=_MINIMAL_CREATE, headers={"Authorization": f"Bearer {token}"})
            pid = created.json()["project"]["id"]
            r = c.get(f"/projects/{pid}/poll-state", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["project_id"], pid)
        self.assertIn("graph_revision", body)
        self.assertIn("timeline_revision", body)
        self.assertIn("fact_count", body)
        self.assertIn("intent_count", body)
        self.assertIn("hint_count", body)
        self.assertNotIn("facts", body)
        self.assertNotIn("intents", body)
        self.assertNotIn("hints", body)
        self.assertNotIn("proxy", body)

    def test_graph_delta_returns_empty_when_revisions_are_current(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            created = c.post("/projects", json=_MINIMAL_CREATE, headers={"Authorization": f"Bearer {token}"})
            pid = created.json()["project"]["id"]
            state = c.get(f"/projects/{pid}/poll-state", headers={"Authorization": f"Bearer {token}"}).json()
            r = c.get(
                f"/projects/{pid}/graph?after_graph_revision={state['graph_revision']}&after_timeline_revision={state['timeline_revision']}",
                headers={"Authorization": f"Bearer {token}"},
            )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["facts"], [])
        self.assertEqual(body["intents"], [])
        self.assertEqual(body["hints"], [])

    def test_hint_only_bumps_timeline_revision(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            created = c.post("/projects", json=_MINIMAL_CREATE, headers={"Authorization": f"Bearer {token}"})
            pid = created.json()["project"]["id"]
            before = c.get(f"/projects/{pid}/poll-state", headers={"Authorization": f"Bearer {token}"}).json()
            hint = c.post(
                f"/projects/{pid}/hints",
                json={"content": "check auth edge case", "creator": "worker_a"},
                headers={"Authorization": f"Bearer {token}"},
            )
            after = c.get(f"/projects/{pid}/poll-state", headers={"Authorization": f"Bearer {token}"}).json()
        self.assertEqual(hint.status_code, 201)
        self.assertEqual(after["graph_revision"], before["graph_revision"])
        self.assertGreater(after["timeline_revision"], before["timeline_revision"])

    def test_intent_lifecycle_bumps_graph_revision(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            created = c.post("/projects", json=_MINIMAL_CREATE, headers={"Authorization": f"Bearer {token}"})
            pid = created.json()["project"]["id"]
            before = c.get(f"/projects/{pid}/poll-state", headers={"Authorization": f"Bearer {token}"}).json()
            created_intent = c.post(
                f"/projects/{pid}/intents",
                json={"from": ["origin"], "description": "investigate", "creator": "worker_a", "worker": None},
                headers={"Authorization": f"Bearer {token}"},
            )
            intent_id = created_intent.json()["id"]
            claimed = c.post(
                f"/projects/{pid}/intents/{intent_id}/claim",
                json={"worker": "worker_a"},
                headers={"Authorization": f"Bearer {token}"},
            )
            after_claim = c.get(f"/projects/{pid}/poll-state", headers={"Authorization": f"Bearer {token}"}).json()
            released = c.post(
                f"/projects/{pid}/intents/{intent_id}/release",
                json={"worker": "worker_a"},
                headers={"Authorization": f"Bearer {token}"},
            )
            after_release = c.get(f"/projects/{pid}/poll-state", headers={"Authorization": f"Bearer {token}"}).json()
        self.assertEqual(created_intent.status_code, 201)
        self.assertEqual(claimed.status_code, 200)
        self.assertEqual(released.status_code, 200)
        self.assertGreater(after_claim["graph_revision"], before["graph_revision"])
        self.assertGreater(after_release["graph_revision"], after_claim["graph_revision"])

    def test_conclude_and_title_update_bump_expected_revisions(self) -> None:
        with self._client() as c:
            token = _login_token(c)
            created = c.post("/projects", json=_MINIMAL_CREATE, headers={"Authorization": f"Bearer {token}"})
            pid = created.json()["project"]["id"]
            initial = c.get(f"/projects/{pid}/poll-state", headers={"Authorization": f"Bearer {token}"}).json()
            created_intent = c.post(
                f"/projects/{pid}/intents",
                json={"from": ["origin"], "description": "investigate", "creator": "worker_a", "worker": "worker_a"},
                headers={"Authorization": f"Bearer {token}"},
            )
            intent_id = created_intent.json()["id"]
            c.post(
                f"/projects/{pid}/intents/{intent_id}/conclude",
                json={"worker": "worker_a", "description": "new fact"},
                headers={"Authorization": f"Bearer {token}"},
            )
            after_conclude = c.get(f"/projects/{pid}/poll-state", headers={"Authorization": f"Bearer {token}"}).json()
            c.put(
                f"/projects/{pid}/title",
                json={"title": "renamed"},
                headers={"Authorization": f"Bearer {token}"},
            )
            after_title = c.get(f"/projects/{pid}/poll-state", headers={"Authorization": f"Bearer {token}"}).json()
        self.assertGreater(after_conclude["graph_revision"], initial["graph_revision"])
        self.assertGreater(after_conclude["timeline_revision"], initial["timeline_revision"])
        self.assertEqual(after_title["graph_revision"], after_conclude["graph_revision"])
        self.assertGreater(after_title["timeline_revision"], after_conclude["timeline_revision"])

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

    def test_llm_event_cards_page_token_is_scoped_to_execution(self) -> None:
        from cairn.server.observability.event_card_service import _CardPageState, _decode_page_token, _encode_page_token

        token = _encode_page_token(
            _CardPageState(
                project_id="proj_cards",
                execution_id="exec_cards_a",
                event_kinds_mode="include",
                event_kinds=("agent_message",),
                offset=2,
            )
        )

        with self.assertRaisesRegex(ValueError, "page token does not match query"):
            _decode_page_token(
                token,
                project_id="proj_cards",
                execution_id="exec_cards_b",
                event_kinds_mode="include",
                event_kinds=("agent_message",),
            )
