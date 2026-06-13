"""End-to-end auth surface tests.

Exercises the real FastAPI app via ``TestClient`` so the global
``_enforce_auth`` dependency is on the critical path. Covers:

  * login with good / bad credentials
  * bearer-required endpoints reject unauthenticated requests with 401
  * bearer-required endpoints accept a valid token
  * expired tokens are rejected
  * refresh issues a new token
  * superuser-only registration
  * dispatcher-style bearer token (CAIRN_API_TOKEN-style) works against
    a project listing
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

from helpers import TempYamlConfig, reset_postgres_db


class AuthTestHarness:
    def __init__(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._attachments_root = Path(self._tmpdir.name) / "attachments"
        self._project_files_root = Path(self._tmpdir.name) / "project-files"
        self._yaml = TempYamlConfig()
        self._yaml.dispatch["server"]["auth"]["jwt_secret"] = "test-secret-do-not-use-in-prod"
        self._yaml.dispatch["server"]["auth"]["dispatcher_api_token"] = ""
        self._yaml.dispatch["server"]["paths"]["attachments_root"] = str(self._attachments_root)
        self._yaml.dispatch["server"]["paths"]["project_files_root"] = str(self._project_files_root)
        self._yaml.__enter__()

        from cairn.server import db
        reset_postgres_db()
        self.db = db

    def close(self) -> None:
        from cairn.server import db
        db.reset_for_tests()
        self._yaml.__exit__(None, None, None)
        self._tmpdir.cleanup()

    def client(self):
        from fastapi.testclient import TestClient

        from cairn.server.app import app
        return TestClient(app)

    def reset_users(self) -> None:
        from cairn.server import db
        from cairn.server.repositories import sql
        with db.session_scope() as conn:
            sql.execute(conn, "DELETE FROM users")


class AuthSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.harness = AuthTestHarness()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.harness.close()

    def setUp(self) -> None:
        self.harness.reset_users()
        from cairn.server.routers import auth as auth_router
        auth_router._reset_login_rate_limit_for_tests()
        self.client = self.harness.client()

    def test_login_public_does_not_require_token(self) -> None:
        r = self.client.post("/auth/login", json={})
        self.assertIn(r.status_code, (400, 422))

    def test_protected_route_without_token_returns_401(self) -> None:
        r = self.client.get("/projects")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.headers.get("www-authenticate"), "Bearer")

    def test_protected_route_with_garbage_token_returns_401(self) -> None:
        r = self.client.get("/projects", headers={"Authorization": "Bearer garbage"})
        self.assertEqual(r.status_code, 401)

    def _seed_user(self, email, password, *, is_superuser=False):
        from cairn.server.security.passwords import hash_password
        from cairn.server.security.users import create
        return create(email, hash_password(password), is_superuser=is_superuser).id

    def test_login_good_credentials_issues_token(self) -> None:
        self._seed_user("alice@example.com", "correcthorse")
        r = self.client.post(
            "/auth/login", json={"email": "alice@example.com", "password": "correcthorse"}
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("access_token", body)
        self.assertEqual(body["token_type"], "bearer")
        self.assertEqual(body["user"]["email"], "alice@example.com")

    def test_login_bad_password_returns_401(self) -> None:
        self._seed_user("alice@example.com", "correcthorse")
        r = self.client.post(
            "/auth/login", json={"email": "alice@example.com", "password": "WRONG"}
        )
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"], "invalid credentials")

    def test_login_unknown_user_returns_401(self) -> None:
        r = self.client.post(
            "/auth/login", json={"email": "ghost@example.com", "password": "whatever"}
        )
        self.assertEqual(r.status_code, 401)

    def test_me_with_valid_token_returns_user(self) -> None:
        self._seed_user("bob@example.com", "battery-staple")
        token = self.client.post(
            "/auth/login", json={"email": "bob@example.com", "password": "battery-staple"}
        ).json()["access_token"]
        r = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["email"], "bob@example.com")
        self.assertNotIn("hashed_password", r.json())

    def test_valid_token_unlocks_protected_route(self) -> None:
        self._seed_user("carol@example.com", "open-sesame")
        token = self.client.post(
            "/auth/login", json={"email": "carol@example.com", "password": "open-sesame"}
        ).json()["access_token"]
        r = self.client.get("/projects", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_expired_token_returns_401(self) -> None:
        from cairn.server.security.jwt import issue_token
        expired = issue_token("u_doesnotmatter", lifetime_seconds=-10)
        r = self.client.get("/projects", headers={"Authorization": f"Bearer {expired}"})
        self.assertEqual(r.status_code, 401)

    def test_refresh_issues_new_token(self) -> None:
        self._seed_user("dan@example.com", "purple-rain")
        token_v1 = self.client.post(
            "/auth/login", json={"email": "dan@example.com", "password": "purple-rain"}
        ).json()["access_token"]
        r = self.client.post(
            "/auth/refresh", headers={"Authorization": f"Bearer {token_v1}"}
        )
        self.assertEqual(r.status_code, 200)
        token_v2 = r.json()["access_token"]
        self.assertNotEqual(token_v1, token_v2)
        r2 = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token_v2}"})
        self.assertEqual(r2.status_code, 200)

    def test_register_requires_superuser(self) -> None:
        self._seed_user("alice@example.com", "alice-password", is_superuser=False)
        token = self.client.post(
            "/auth/login", json={"email": "alice@example.com", "password": "alice-password"}
        ).json()["access_token"]
        r = self.client.post(
            "/auth/users",
            json={"email": "bob@example.com", "password": "bob-password-123"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(r.status_code, 403)

    def test_register_succeeds_as_superuser(self) -> None:
        self._seed_user("admin@example.com", "admin-password", is_superuser=True)
        token = self.client.post(
            "/auth/login", json={"email": "admin@example.com", "password": "admin-password"}
        ).json()["access_token"]
        r = self.client.post(
            "/auth/users",
            json={"email": "user@example.com", "password": "user-password-456"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["email"], "user@example.com")

    def test_register_duplicate_email_returns_409(self) -> None:
        self._seed_user("admin@example.com", "admin-pwd", is_superuser=True)
        self._seed_user("dup@example.com", "dup-pwd", is_superuser=False)
        token = self.client.post(
            "/auth/login", json={"email": "admin@example.com", "password": "admin-pwd"}
        ).json()["access_token"]
        r = self.client.post(
            "/auth/users",
            json={"email": "dup@example.com", "password": "another-pwd"},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(r.status_code, 409)

    def test_dispatcher_style_bearer_token_works(self) -> None:
        from cairn.server.security.jwt import issue_token
        self._seed_user("admin@example.com", "admin-pwd", is_superuser=True)
        service_token = issue_token("dispatcher-service", extra_claims={"role": "service"})
        r = self.client.get("/projects", headers={"Authorization": f"Bearer {service_token}"})
        self.assertEqual(r.status_code, 200)

    def test_login_rate_limit_kicks_in(self) -> None:
        for _ in range(10):
            r = self.client.post(
                "/auth/login", json={"email": "ghost@example.com", "password": "x"}
            )
            self.assertIn(r.status_code, (401, 429))
        r = self.client.post(
            "/auth/login", json={"email": "ghost@example.com", "password": "x"}
        )
        self.assertEqual(r.status_code, 429)


if __name__ == "__main__":
    unittest.main()
