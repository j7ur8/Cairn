"""Tiny local health server for the dispatcher process.

Exposes two endpoints on loopback only by default:

* ``GET /healthz`` -> JSON with last tick age
* ``GET /metrics`` -> Prometheus text using the shared registry

The server is deliberately small and synchronous. It runs in a daemon
thread so it does not block dispatcher shutdown.
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cairn.shared.observability.metrics import render_metrics


@dataclass(slots=True)
class DispatcherHealthState:
    last_tick_at: Callable[[], float | None]

    def payload(self) -> dict[str, object]:
        errors: list[str] = []
        try:
            last_tick = self.last_tick_at()
        except Exception as exc:  # noqa: BLE001 - health endpoint must not crash
            last_tick = None
            errors.append(f"last_tick_at: {type(exc).__name__}: {exc}")
        payload: dict[str, object] = {
            "status": "degraded" if errors else "ok",
            "last_tick_age": None if last_tick is None else max(0.0, time.time() - last_tick),
        }
        if errors:
            payload["errors"] = errors
        return payload


class DispatcherHealthServer:
    def __init__(
        self,
        host: str,
        port: int,
        state: DispatcherHealthState,
        *,
        reload_handler: Callable[[str | None], dict[str, object]] | None = None,
    ):
        self.host = host
        self.port = port
        self.state = state
        self.reload_handler = reload_handler
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int] | None:
        if self._server is None:
            return None
        address = self._server.server_address
        return str(address[0]), int(address[1])

    def start(self) -> None:
        if self._server is not None:
            return
        state = self.state
        reload_handler = self.reload_handler

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib API
                if self.path == "/healthz":
                    body = json.dumps(state.payload(), separators=(",", ":")).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/metrics":
                    body, content_type = render_metrics()
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

            def do_POST(self) -> None:  # noqa: N802 - stdlib API
                if self.path == "/reload" and reload_handler is not None:
                    auth = self.headers.get("Authorization")
                    try:
                        payload = reload_handler(auth)
                        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                        status = 200
                    except PermissionError as exc:
                        body = json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":")).encode("utf-8")
                        status = 403
                    except Exception as exc:  # noqa: BLE001
                        body = json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":")).encode("utf-8")
                        status = 400
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="cairn-dispatcher-health",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._server = None
        self._thread = None
