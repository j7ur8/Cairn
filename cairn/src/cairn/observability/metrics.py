"""Prometheus metrics shared by the server and the dispatcher.

We deliberately use a custom :class:`CollectorRegistry` rather than
the default global one. That makes the registry explicit in
``/metrics`` output and avoids accidental cross-test contamination
when the process is reloaded in long-running test harnesses.
"""
from __future__ import annotations

try:
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )
    from prometheus_client.exposition import CONTENT_TYPE_LATEST
except ImportError:  # pragma: no cover - exercised only without optional dependency
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"

    class CollectorRegistry:
        def __init__(self, *args, **kwargs):
            pass

    class _NoopMetric:
        def __init__(self, *args, **kwargs):
            pass

        def labels(self, *args, **kwargs):
            return self

        def inc(self, *args, **kwargs) -> None:
            return None

        def set(self, *args, **kwargs) -> None:
            return None

        def observe(self, *args, **kwargs) -> None:
            return None

    Counter = Gauge = Histogram = _NoopMetric

    def generate_latest(registry) -> bytes:
        return b""


REGISTRY = CollectorRegistry(auto_describe=True)

# HTTP request counter / latency
HTTP_REQUESTS = Counter(
    "cairn_http_requests_total",
    "Number of HTTP requests handled by the server, labeled by method, path and status.",
    labelnames=("method", "path", "status"),
    registry=REGISTRY,
)
HTTP_LATENCY = Histogram(
    "cairn_http_request_duration_seconds",
    "Latency of HTTP requests handled by the server.",
    labelnames=("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

# Dispatcher scheduling
DISPATCHER_TICKS = Counter(
    "cairn_dispatcher_ticks_total",
    "Number of scheduler ticks executed.",
    registry=REGISTRY,
)
DISPATCHER_INFLIGHT = Gauge(
    "cairn_dispatcher_inflight_tasks",
    "Tasks currently executing in the dispatcher thread pool.",
    registry=REGISTRY,
)
DISPATCHER_TASKS = Counter(
    "cairn_dispatcher_tasks_total",
    "Tasks started by the dispatcher, labeled by task_type and outcome.",
    labelnames=("task_type", "outcome"),
    registry=REGISTRY,
)
DISPATCHER_OVERFLOW = Counter(
    "cairn_dispatcher_overflow_total",
    "Times a worker request was rejected because the pool was full.",
    labelnames=("reason",),
    registry=REGISTRY,
)
WORKER_UNHEALTHY_SINCE = Gauge(
    "cairn_worker_unhealthy_since_seconds",
    "Unix timestamp when a worker was most recently marked unhealthy; 0 means healthy.",
    labelnames=("worker",),
    registry=REGISTRY,
)

# Auth
AUTH_LOGINS = Counter(
    "cairn_auth_logins_total",
    "Login attempts, labeled by outcome (success / bad_credentials / rate_limited).",
    labelnames=("outcome",),
    registry=REGISTRY,
)


def render_metrics() -> tuple[bytes, str]:
    """Return ``(body, content_type)`` for the ``GET /metrics`` endpoint."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
