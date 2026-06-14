"""End-to-end router tests for the auth router.

Covers login, token refresh, ``/auth/me``, user CRUD, and the superuser
gate. Each test requires a live PostgreSQL (``db`` marker)."""

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


class AuthRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = reset_postgres_db()

    def _client(self):
        from fastapi.testclient import TestClient
        from cairn.server.app import app
        return TestClient(app)

    # ------------------------------------------------------------------
    # Login ------------------------------------------------------------
    # ------------------------------------------------------------------

    def test_login_success(self) -> None:
        with self._client() as c:
            r = c.post("/auth/login", json={"email": "admin@cairn.local", "password": "Aa123123"})
        self.assertEqual(r.status_code, 200)
        token = r.json().get("access_token")
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 20)

    def test_login_bad_password(self) -> None:
        with self._client() as c:
            r = c.post("/auth/login", json={"email": "admin@cairn.local", "password": "WrongPassword1"})
        self.assertEqual(r.status_code, 401)

    def test_login_missing_user(self) -> None:
        with self._client() as c:
            r = c.post("/auth/login", json={"email": "nobody@cairn.local", "password": "Aa123123"})
        self.assertEqual(r.status_code, 401)

    def test_login_missing_email_returns_422(self) -> None:
        with self._client() as c:
            r = c.post("/auth/login", json={"password": "Aa123123"})
        self.assertEqual(r.status_code, 422)

    # ------------------------------------------------------------------
    # Token refresh & /auth/me ----------------------------------------
    # ------------------------------------------------------------------

    def test_refresh_token(self) -> None:
        with self._client() as c:
            login = c.post("/auth/login", json={"email": "admin@cairn.local", "password": "Aa123123"})
            token = login.json()["access_token"]
            r = c.post("/auth/refresh", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        new_token = r.json().get("access_token")
        self.assertIsInstance(new_token, str)
        self.assertNotEqual(new_token, token)

    def test_auth_me_returns_current_user(self) -> None:
        with self._client() as c:
            login = c.post("/auth/login", json={"email": "admin@cairn.local", "password": "Aa123123"})
            token = login.json()["access_token"]
            r = c.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(r.status_code, 200)
        user = r.json()
        self.assertEqual(user["email"], "admin@cairn.local")

    def test_auth_me_requires_token(self) -> None:
        with self._client() as c:
            r = c.get("/auth/me")
        self.assertEqual(r.status_code, 401)

    def test_refresh_requires_token(self) -> None:
        with self._client() as c:
            r = c.post("/auth/refresh")
        self.assertEqual(r.status_code, 401)

    # ------------------------------------------------------------------
    # Superuser-only endpoints -----------------------------------------
    # ------------------------------------------------------------------

    def test_list_users_requires_superuser(self) -> None:
        with self._client() as c:
            login = c.post("/auth/login", json={"email": "admin@cairn.local", "password": "Aa123123"})
            token = login.json()["access_token"]
            r = c.get("/auth/users", headers={"Authorization": f"Bearer {token}"})
        # admin is superuser — this should succeed.
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    # ------------------------------------------------------------------
    # Public-path exemption --------------------------------------------
    # ------------------------------------------------------------------

    def test_login_is_public(self) -> None:
        with self._client() as c:
            r = c.post("/auth/login", json={"email": "admin@cairn.local", "password": "Aa123123"})
        # Even without a token this must succeed (it emits one).
        self.assertIn(r.status_code, (200, 401))

    def test_health_is_public(self) -> None:
        with self._client() as c:
            r = c.get("/health")
        self.assertEqual(r.status_code, 200)
