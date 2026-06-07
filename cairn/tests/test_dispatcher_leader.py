from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class DispatcherLeaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        from cairn.server import db
        db._db_path = None
        db.close_thread_conn()
        db.configure(Path(self.tmp.name))
        self.db = db

    def tearDown(self) -> None:
        self.db.close_thread_conn()
        self.db._db_path = None
        os.unlink(self.tmp.name)

    def test_single_dispatcher_acquires(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        leader = DispatcherLeader(name="test", holder="a", ttl_seconds=10)
        self.assertTrue(leader.acquire())
        self.assertTrue(leader.is_leader)
        self.assertEqual(leader.current_holder(), "a")

    def test_second_dispatcher_does_not_steal_fresh_lock(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        a = DispatcherLeader(name="test", holder="a", ttl_seconds=10)
        b = DispatcherLeader(name="test", holder="b", ttl_seconds=10)
        self.assertTrue(a.acquire())
        self.assertFalse(b.acquire())
        self.assertEqual(a.current_holder(), "a")

    def test_stale_lock_can_be_stolen(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        a = DispatcherLeader(name="test", holder="a", ttl_seconds=0.01)
        b = DispatcherLeader(name="test", holder="b", ttl_seconds=0.01)
        self.assertTrue(a.acquire())
        time.sleep(0.03)
        self.assertTrue(b.acquire())
        self.assertEqual(b.current_holder(), "b")

    def test_heartbeat_renews_lock(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        a = DispatcherLeader(name="test", holder="a", ttl_seconds=10)
        self.assertTrue(a.acquire())
        self.assertTrue(a.heartbeat())
        self.assertTrue(a.is_leader)

    def test_release_unlocks(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        a = DispatcherLeader(name="test", holder="a", ttl_seconds=10)
        b = DispatcherLeader(name="test", holder="b", ttl_seconds=10)
        self.assertTrue(a.acquire())
        a.release()
        self.assertTrue(b.acquire())
        self.assertEqual(b.current_holder(), "b")

    def test_acquire_retries_transient_sqlite_database_error(self) -> None:
        import sqlite3
        from cairn.dispatcher.leadership import DispatcherLeader

        leader = DispatcherLeader(name="test", holder="a", ttl_seconds=10)
        real_tx = self.db.with_immediate_tx
        calls = {"count": 0}

        @contextmanager
        def flaky_tx():
            calls["count"] += 1
            if calls["count"] == 1:
                raise sqlite3.DatabaseError("database disk image is malformed")
            with real_tx() as conn:
                yield conn

        with patch("cairn.dispatcher.leadership.with_immediate_tx", flaky_tx), patch("time.sleep"):
            self.assertTrue(leader.acquire())
        self.assertEqual(calls["count"], 2)
        self.assertEqual(leader.current_holder(), "a")

    def test_acquire_raises_diagnostic_after_retries_exhausted(self) -> None:
        import sqlite3
        from cairn.dispatcher.leadership import DispatcherLeader

        leader = DispatcherLeader(name="test", holder="a", ttl_seconds=10)

        @contextmanager
        def broken_tx():
            raise sqlite3.DatabaseError("database disk image is malformed")
            yield

        with patch("cairn.dispatcher.leadership.with_immediate_tx", broken_tx), patch("time.sleep"):
            with self.assertRaises(RuntimeError) as ctx:
                leader.acquire()
        message = str(ctx.exception)
        self.assertIn("database disk image is malformed", message)
        self.assertIn("wal_exists=", message)
        self.assertIn("cairn db diagnose", message)

    def test_current_holder_retries_transient_sqlite_database_error(self) -> None:
        import sqlite3
        from cairn.dispatcher.leadership import DispatcherLeader

        leader = DispatcherLeader(name="test", holder="a", ttl_seconds=10)
        self.assertTrue(leader.acquire())
        real_get_conn = self.db.get_conn
        calls = {"count": 0}

        @contextmanager
        def flaky_get_conn():
            calls["count"] += 1
            if calls["count"] == 1:
                raise sqlite3.DatabaseError("database disk image is malformed")
            with real_get_conn() as conn:
                yield conn

        with patch("cairn.dispatcher.leadership.get_conn", flaky_get_conn), patch("time.sleep"):
            self.assertEqual(leader.current_holder(), "a")
        self.assertEqual(calls["count"], 2)

    def test_is_expired_retries_transient_sqlite_database_error(self) -> None:
        import sqlite3
        from cairn.dispatcher.leadership import DispatcherLeader

        leader = DispatcherLeader(name="test", holder="a", ttl_seconds=10)
        self.assertTrue(leader.acquire())
        real_get_conn = self.db.get_conn
        calls = {"count": 0}

        @contextmanager
        def flaky_get_conn():
            calls["count"] += 1
            if calls["count"] == 1:
                raise sqlite3.DatabaseError("database disk image is malformed")
            with real_get_conn() as conn:
                yield conn

        with patch("cairn.dispatcher.leadership.get_conn", flaky_get_conn), patch("time.sleep"):
            self.assertFalse(leader.is_expired())
        self.assertEqual(calls["count"], 2)


if __name__ == "__main__":
    unittest.main()
