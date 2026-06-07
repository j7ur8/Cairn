from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class LeaderStepDownTests(unittest.TestCase):
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

    def test_check_health_passes_for_held_lock(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        a = DispatcherLeader(name="t", holder="a", ttl_seconds=10)
        self.assertTrue(a.acquire())
        # No raise when we still own the lock.
        a.check_health()

    def test_check_health_raises_when_lock_taken(self) -> None:
        from cairn.dispatcher.leadership import (
            DispatcherLeader,
            LeadershipLost,
        )

        a = DispatcherLeader(name="t", holder="a", ttl_seconds=10)
        b = DispatcherLeader(name="t", holder="b", ttl_seconds=10)
        self.assertTrue(a.acquire())
        # Simulate b stealing the lock row.
        a.release()
        self.assertTrue(b.acquire())
        with self.assertRaises(LeadershipLost):
            a.check_health()

    def test_check_health_raises_when_heartbeat_stale(self) -> None:
        from cairn.dispatcher.leadership import (
            DispatcherLeader,
            LeadershipLost,
        )

        a = DispatcherLeader(name="t", holder="a", ttl_seconds=0.01)
        self.assertTrue(a.acquire())
        time.sleep(0.05)
        with self.assertRaises(LeadershipLost):
            a.check_health()

    def test_acquired_context_blocks_until_release(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        a = DispatcherLeader(name="t", holder="a", ttl_seconds=10)
        b = DispatcherLeader(name="t", holder="b", ttl_seconds=10)
        # a acquires then releases
        with a.acquired(retry_interval=0.01):
            pass
        # b can now acquire in its own context
        with b.acquired(retry_interval=0.01):
            self.assertTrue(b.is_leader)
        self.assertFalse(b.is_leader)

    def test_acquired_context_releases_on_exception(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        a = DispatcherLeader(name="t", holder="a", ttl_seconds=10)
        b = DispatcherLeader(name="t", holder="b", ttl_seconds=10)
        with self.assertRaises(RuntimeError):
            with a.acquired(retry_interval=0.01):
                raise RuntimeError("boom")
        # Lock must be released; b can grab it.
        with b.acquired(retry_interval=0.01):
            self.assertTrue(b.is_leader)


if __name__ == "__main__":
    unittest.main()
