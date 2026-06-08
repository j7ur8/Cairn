from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class FakeClient:
    def __init__(self) -> None:
        from cairn.dispatcher.protocol.client import ApiResult

        self.ApiResult = ApiResult
        self.holder: str | None = None
        self.fail_current = False
        self.release_calls = 0
        self.current_calls = 0

    def dispatcher_lock_acquire(self, name: str, holder: str, ttl_seconds: float):
        if self.holder is None or self.holder == holder:
            self.holder = holder
            return self.ApiResult(200, {"acquired": True, "holder": holder, "held": True})
        return self.ApiResult(200, {"acquired": False, "holder": self.holder, "held": False})

    def dispatcher_lock_heartbeat(self, name: str, holder: str):
        held = self.holder == holder
        return self.ApiResult(200, {"held": held, "holder": holder if held else None})

    def dispatcher_lock_release(self, name: str, holder: str):
        self.release_calls += 1
        if self.holder == holder:
            self.holder = None
            return self.ApiResult(200, {"released": True})
        return self.ApiResult(200, {"released": False})

    def dispatcher_lock_current(self, name: str):
        self.current_calls += 1
        if self.fail_current:
            return self.ApiResult(503, {"status": "degraded"})
        return self.ApiResult(200, {"holder": self.holder, "held": self.holder is not None})


class DispatcherLeaderTests(unittest.TestCase):
    def test_single_dispatcher_acquires(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        client = FakeClient()
        leader = DispatcherLeader(client=client, name="test", holder="a", ttl_seconds=10)
        self.assertTrue(leader.acquire())
        self.assertTrue(leader.is_leader)
        self.assertEqual(leader.current_holder(), "a")

    def test_second_dispatcher_does_not_steal_fresh_lock(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        client = FakeClient()
        a = DispatcherLeader(client=client, name="test", holder="a", ttl_seconds=10)
        b = DispatcherLeader(client=client, name="test", holder="b", ttl_seconds=10)
        self.assertTrue(a.acquire())
        self.assertFalse(b.acquire())
        self.assertEqual(a.current_holder(), "a")

    def test_heartbeat_renews_lock(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        client = FakeClient()
        a = DispatcherLeader(client=client, name="test", holder="a", ttl_seconds=10)
        self.assertTrue(a.acquire())
        self.assertTrue(a.heartbeat())
        self.assertTrue(a.is_leader)

    def test_heartbeat_loss_marks_follower(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        client = FakeClient()
        a = DispatcherLeader(client=client, name="test", holder="a", ttl_seconds=10)
        self.assertTrue(a.acquire())
        client.holder = "b"
        self.assertFalse(a.heartbeat())
        self.assertFalse(a.is_leader)

    def test_release_unlocks(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        client = FakeClient()
        a = DispatcherLeader(client=client, name="test", holder="a", ttl_seconds=10)
        b = DispatcherLeader(client=client, name="test", holder="b", ttl_seconds=10)
        self.assertTrue(a.acquire())
        a.release()
        self.assertTrue(b.acquire())
        self.assertEqual(b.current_holder(), "b")

    def test_is_leader_uses_cached_heartbeat_age(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        client = FakeClient()
        leader = DispatcherLeader(client=client, name="test", holder="a", ttl_seconds=0.01)
        self.assertTrue(leader.acquire())
        time.sleep(0.03)
        self.assertFalse(leader.is_leader)

    def test_check_health_raises_on_degraded_server(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader, LeadershipLost

        client = FakeClient()
        leader = DispatcherLeader(client=client, name="test", holder="a", ttl_seconds=10)
        self.assertTrue(leader.acquire())
        client.fail_current = True
        with self.assertRaises(LeadershipLost):
            leader.check_health()
        self.assertFalse(leader.is_leader)

    def test_acquired_context_release_does_not_call_current_holder(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        client = FakeClient()
        leader = DispatcherLeader(client=client, name="test", holder="a", ttl_seconds=10)
        with leader.acquired(retry_interval=0.01):
            self.assertTrue(leader.is_leader)
        self.assertEqual(client.release_calls, 1)
        self.assertEqual(client.current_calls, 0)
        self.assertFalse(leader._is_leader)


if __name__ == "__main__":
    unittest.main()
