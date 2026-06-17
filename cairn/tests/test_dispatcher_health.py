from __future__ import annotations

import json
import unittest
import urllib.request


class DispatcherHealthServerTests(unittest.TestCase):
    def test_healthz_and_metrics(self) -> None:
        from cairn.dispatcher.health_server import DispatcherHealthServer, DispatcherHealthState
        from cairn.shared.observability.metrics import DISPATCHER_TICKS

        last_tick = 123.0
        state = DispatcherHealthState(
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
            self.assertIn("last_tick_age", body)

            DISPATCHER_TICKS.inc()
            with urllib.request.urlopen(f"http://{host}:{port}/metrics", timeout=5) as resp:
                text = resp.read().decode("utf-8")
            self.assertIn("cairn_dispatcher_ticks_total", text)
        finally:
            server.stop()

    def test_healthz_returns_degraded_when_state_callbacks_fail(self) -> None:
        from cairn.dispatcher.health_server import DispatcherHealthServer, DispatcherHealthState

        state = DispatcherHealthState(
            last_tick_at=lambda: (_ for _ in ()).throw(RuntimeError("tick failed")),
        )
        server = DispatcherHealthServer("127.0.0.1", 0, state)
        try:
            server.start()
            assert server.address is not None
            host, port = server.address
            with urllib.request.urlopen(f"http://{host}:{port}/healthz", timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(body["status"], "degraded")
            self.assertIn("tick failed", repr(body["errors"]))
        finally:
            server.stop()

    def test_mcp_probe_post_forwards_auth_and_json_body(self) -> None:
        from cairn.dispatcher.health_server import DispatcherHealthServer, DispatcherHealthState

        captured = {}

        def handler(auth, body):
            captured["auth"] = auth
            captured["body"] = body
            return {"results": [{"capability_id": "m", "status": "ok", "message": "ready"}]}

        state = DispatcherHealthState(last_tick_at=lambda: 123.0)
        server = DispatcherHealthServer("127.0.0.1", 0, state, mcp_probe_handler=handler)
        try:
            server.start()
            assert server.address is not None
            host, port = server.address
            request = urllib.request.Request(
                f"http://{host}:{port}/mcp-probe",
                data=json.dumps({"server_ids": ["m"]}).encode("utf-8"),
                method="POST",
                headers={"Authorization": "Bearer token", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(body["results"][0]["status"], "ok")
            self.assertEqual(captured["auth"], "Bearer token")
            self.assertEqual(captured["body"], {"server_ids": ["m"]})
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
