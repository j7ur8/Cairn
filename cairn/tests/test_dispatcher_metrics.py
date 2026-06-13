from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class DispatcherMetricTests(unittest.TestCase):
    def test_overflow_counter_renders(self) -> None:
        from cairn.shared.observability.metrics import (
            DISPATCHER_OVERFLOW,
            render_metrics,
        )

        before = render_metrics()[0].decode()
        DISPATCHER_OVERFLOW.labels(reason="max_workers").inc()
        DISPATCHER_OVERFLOW.labels(reason="max_workers").inc()
        body = render_metrics()[0].decode()
        # Counter should now show at least 2 for the labelled reason.
        self.assertIn("cairn_dispatcher_overflow_total", body)
        self.assertIn('reason="max_workers"', body)
        # And the body length must have grown.
        self.assertGreater(len(body), len(before))

    def test_worker_unhealthy_gauge_renders(self) -> None:
        from cairn.shared.observability.metrics import (
            WORKER_UNHEALTHY_SINCE,
            render_metrics,
        )

        WORKER_UNHEALTHY_SINCE.labels(worker="codex").set(0)
        body = render_metrics()[0].decode()
        self.assertIn("cairn_worker_unhealthy_since_seconds", body)
        self.assertIn('worker="codex"', body)

if __name__ == "__main__":
    unittest.main()
