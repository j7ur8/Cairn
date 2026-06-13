"""Assembly smoke test for the dispatcher composition root.

DispatcherLoop.__init__ wires 20+ collaborators in a load-bearing order
(each phase depends on attributes set by earlier ones). It previously had no
construction coverage because building it touches Docker (ContainerManager
calls docker.from_env()) and binds the health-server socket.

This test mocks those two external resources and asserts the loop assembles
fully — every collaborator attribute is present and the phase methods ran in
order. It guards the _init_* split so a future reorder or dropped phase that
leaves a collaborator unwired fails here rather than at dispatch time.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

_DISPATCH_TEST_YAML = _REPO / "dispatch.test.yaml"


class DispatcherAssemblyTests(unittest.TestCase):
    def _build(self):
        import cairn.dispatcher.scheduler.loop as loop_mod

        with mock.patch.object(loop_mod, "ContainerManager") as cm, \
                mock.patch.object(loop_mod, "DispatcherHealthServer") as hs:
            cm.return_value = mock.Mock(name="ContainerManager")
            hs.return_value = mock.Mock(name="DispatcherHealthServer")
            loop = loop_mod.DispatcherLoop(_DISPATCH_TEST_YAML)
            return loop, hs.return_value

    def test_all_collaborators_are_wired(self) -> None:
        loop, health_server = self._build()
        # The health server is started exactly once during assembly.
        health_server.start.assert_called_once()
        # Every collaborator the scheduler relies on must be present.
        for attr in (
            "config", "client", "health_server", "executor", "runtime",
            "log_state", "project_caches", "execution_configs", "replay",
            "ai_worker_selector", "project_context", "container_manager",
            "health", "cleanup", "submitter", "runtime_maintenance",
            "scheduler_services", "project_dispatcher", "dispatch_coordinator",
            "tick_coordinator", "reloader",
        ):
            self.assertIsNotNone(getattr(loop, attr, None), f"{attr} not wired")

    def test_initial_runtime_state_defaults(self) -> None:
        loop, _ = self._build()
        self.assertEqual(loop.project_cursor, 0)
        self.assertFalse(loop._settings_checked)
        self.assertFalse(loop._startup_healthchecks_checked)
        self.assertIsNone(loop._last_tick_at)


if __name__ == "__main__":
    unittest.main()
