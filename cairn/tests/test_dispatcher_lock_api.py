from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class DispatcherLockApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        from cairn.server import db
        from cairn.server.observability import db as obs_db

        db._db_path = None
        db.close_thread_conn()
        db.configure(Path(self.tmp.name) / "main.sqlite")
        obs_db._db_path = None
        obs_db.configure(Path(self.tmp.name) / "obs.sqlite")

        from cairn.server.security.jwt import issue_token

        self.headers = {
            "Authorization": f"Bearer {issue_token('dispatcher-test', extra_claims={'role': 'service'})}",
        }

    def tearDown(self) -> None:
        from cairn.server import db
        from cairn.server.observability import db as obs_db

        db.close_thread_conn()
        db._db_path = None
        obs_db._db_path = None
        self.tmp.cleanup()

    def client(self):
        from fastapi.testclient import TestClient
        from cairn.server.app import app

        return TestClient(app)

    def test_acquire_blocks_fresh_second_holder(self) -> None:
        with self.client() as client:
            r1 = client.post(
                "/dispatcher-lock/acquire",
                headers=self.headers,
                json={"name": "test", "holder": "a", "ttl_seconds": 10},
            )
            r2 = client.post(
                "/dispatcher-lock/acquire",
                headers=self.headers,
                json={"name": "test", "holder": "b", "ttl_seconds": 10},
            )
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json()["acquired"])
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.json()["acquired"])
        self.assertEqual(r2.json()["holder"], "a")

    def test_stale_lock_can_be_stolen(self) -> None:
        with self.client() as client:
            r1 = client.post(
                "/dispatcher-lock/acquire",
                headers=self.headers,
                json={"name": "test", "holder": "a", "ttl_seconds": 0.01},
            )
            time.sleep(0.03)
            r2 = client.post(
                "/dispatcher-lock/acquire",
                headers=self.headers,
                json={"name": "test", "holder": "b", "ttl_seconds": 0.01},
            )
            current = client.get("/dispatcher-lock/current", headers=self.headers, params={"name": "test"})
        self.assertTrue(r1.json()["acquired"])
        self.assertTrue(r2.json()["acquired"])
        self.assertEqual(current.json()["holder"], "b")

    def test_heartbeat_and_release_are_holder_scoped(self) -> None:
        with self.client() as client:
            client.post(
                "/dispatcher-lock/acquire",
                headers=self.headers,
                json={"name": "test", "holder": "a", "ttl_seconds": 10},
            )
            bad_heartbeat = client.post(
                "/dispatcher-lock/heartbeat",
                headers=self.headers,
                json={"name": "test", "holder": "b"},
            )
            bad_release = client.post(
                "/dispatcher-lock/release",
                headers=self.headers,
                json={"name": "test", "holder": "b"},
            )
            current = client.get("/dispatcher-lock/current", headers=self.headers, params={"name": "test"})
            good_release = client.post(
                "/dispatcher-lock/release",
                headers=self.headers,
                json={"name": "test", "holder": "a"},
            )
            empty = client.get("/dispatcher-lock/current", headers=self.headers, params={"name": "test"})
        self.assertFalse(bad_heartbeat.json()["held"])
        self.assertFalse(bad_release.json()["released"])
        self.assertEqual(current.json()["holder"], "a")
        self.assertTrue(good_release.json()["released"])
        self.assertIsNone(empty.json()["holder"])


if __name__ == "__main__":
    unittest.main()
