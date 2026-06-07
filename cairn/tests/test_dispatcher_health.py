from __future__ import annotations

import json
import urllib.request
import unittest


class DispatcherHealthServerTests(unittest.TestCase):
    def test_healthz_and_metrics(self) -> None:
        from cairn.dispatcher.health_server import DispatcherHealthServer, DispatcherHealthState
        from cairn.observability.metrics import DISPATCHER_TICKS

        last_tick = 123.0
        state = DispatcherHealthState(
            is_leader=lambda: True,
            current_holder=lambda: "holder-a",
            last_tick_at=lambda: last_tick,
        )
        server = DispatcherHealthServer("127.0.0.1", 0, state)
        try:
            server.start()
            assert server.address is not None
            host, port = server.address
            with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(body["status"], "ok")
            self.assertTrue(body["is_leader"])
            self.assertEqual(body["current_holder"], "holder-a")

            DISPATCHER_TICKS.inc()
            with urllib.request.urlopen(f"http://{host}:{port}/metrics", timeout=5) as resp:
                text = resp.read().decode("utf-8")
            self.assertIn("cairn_dispatcher_ticks_total", text)
        finally:
            server.stop()

    def test_healthz_returns_degraded_when_state_callbacks_fail(self) -> None:
        from cairn.dispatcher.health_server import DispatcherHealthServer, DispatcherHealthState

        state = DispatcherHealthState(
            is_leader=lambda: (_ for _ in ()).throw(RuntimeError("leader failed")),
            current_holder=lambda: (_ for _ in ()).throw(RuntimeError("holder failed")),
            last_tick_at=lambda: 123.0,
        )
        server = DispatcherHealthServer("127.0.0.1", 0, state)
        try:
            server.start()
            assert server.address is not None
            host, port = server.address
            with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(body["status"], "degraded")
            self.assertFalse(body["is_leader"])
            self.assertIsNone(body["current_holder"])
            self.assertIn("leader failed", repr(body["errors"]))
            self.assertIn("holder failed", repr(body["errors"]))
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
