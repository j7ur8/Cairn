from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class LeaderStepDownTests(unittest.TestCase):
    def _client(self):
        from tests.test_dispatcher_leader import FakeClient

        return FakeClient()

    def test_check_health_passes_for_held_lock(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        client = self._client()
        a = DispatcherLeader(client=client, name="t", holder="a", ttl_seconds=10)
        self.assertTrue(a.acquire())
        a.check_health()

    def test_check_health_raises_when_lock_taken(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader, LeadershipLost

        client = self._client()
        a = DispatcherLeader(client=client, name="t", holder="a", ttl_seconds=10)
        b = DispatcherLeader(client=client, name="t", holder="b", ttl_seconds=10)
        self.assertTrue(a.acquire())
        a.release()
        self.assertTrue(b.acquire())
        with self.assertRaises(LeadershipLost):
            a.check_health()

    def test_check_health_raises_when_heartbeat_stale(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader, LeadershipLost

        client = self._client()
        a = DispatcherLeader(client=client, name="t", holder="a", ttl_seconds=0.01)
        self.assertTrue(a.acquire())
        time.sleep(0.05)
        with self.assertRaises(LeadershipLost):
            a.check_health()

    def test_acquired_context_blocks_until_release(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        client = self._client()
        a = DispatcherLeader(client=client, name="t", holder="a", ttl_seconds=10)
        b = DispatcherLeader(client=client, name="t", holder="b", ttl_seconds=10)
        with a.acquired(retry_interval=0.01):
            pass
        with b.acquired(retry_interval=0.01):
            self.assertTrue(b.is_leader)
        self.assertFalse(b.is_leader)

    def test_acquired_context_releases_on_exception(self) -> None:
        from cairn.dispatcher.leadership import DispatcherLeader

        client = self._client()
        a = DispatcherLeader(client=client, name="t", holder="a", ttl_seconds=10)
        b = DispatcherLeader(client=client, name="t", holder="b", ttl_seconds=10)
        with self.assertRaises(RuntimeError):
            with a.acquired(retry_interval=0.01):
                raise RuntimeError("boom")
        with b.acquired(retry_interval=0.01):
            self.assertTrue(b.is_leader)

    def test_startup_sequence_heartbeats_between_long_steps(self) -> None:
        from cairn.dispatcher.scheduler.loop import DispatcherLoop

        loop = DispatcherLoop.__new__(DispatcherLoop)
        loop._startup_healthchecks_checked = False
        loop._settings_checked = False
        loop._capability_catalog_registered = False
        loop._role_catalog_registered = False
        loop._ai_catalog_synced = False
        loop.futures = {}
        loop.cleanup_futures = {}
        loop.client = MagicMock()
        loop.client.list_projects.return_value = []
        loop.reason_checkpoints = {}
        loop.runtime_project_ids = set()
        loop.worker_unhealthy_until = {}
        loop.config = type("Cfg", (), {"runtime": type("Runtime", (), {"interval": 1})()})()
        loop.leader = MagicMock()
        loop._reap_futures = MagicMock()
        loop._reap_cleanup_futures = MagicMock()
        loop._initialize_reason_checkpoints = MagicMock()
        loop._refresh_runtime_projects = MagicMock()
        loop._cancel_inactive_tasks = MagicMock()
        loop._queue_container_cleanups = MagicMock()
        loop._dispatch_available = MagicMock()
        loop._publish_tick_metrics = MagicMock()
        loop.run_startup_healthchecks = MagicMock()
        loop._validate_server_settings = MagicMock()
        loop._register_capability_catalog = MagicMock()
        loop._register_role_catalog = MagicMock()
        loop._sync_ai_catalog_from_dispatch_yaml = MagicMock()

        DispatcherLoop._run_leader_iteration(loop, once=True)

        self.assertGreaterEqual(loop.leader.heartbeat.call_count, 5)


if __name__ == "__main__":
    unittest.main()
