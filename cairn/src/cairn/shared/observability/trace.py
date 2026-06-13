"""Per-request and per-task trace id propagation.

A single ``ContextVar`` holds the current trace id. The HTTP
middleware sets it from the inbound ``X-Request-Id`` (or generates a
new one) on the way in and the same value rides the outbound
``X-Request-Id`` header on the way out. Background work and the
dispatcher loop can mint their own ids via :func:`new_trace_id`.
"""
from __future__ import annotations

import contextvars
import uuid

trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "cairn_trace_id", default=None,
)


def get_trace_id() -> str | None:
    return trace_id_var.get()


def set_trace_id(value: str | None) -> contextvars.Token[str | None]:
    return trace_id_var.set(value)


def reset_trace_id(token: contextvars.Token[str | None]) -> None:
    trace_id_var.reset(token)


def new_trace_id() -> str:
    """Mint a fresh trace id and bind it to the current context."""
    tid = uuid.uuid4().hex
    trace_id_var.set(tid)
    return tid


class TraceIdFilter:
    """Logging filter that injects the current trace id into every record.

    Always set on the root handler by :func:`configure_logging` so the
    formatter can render ``trace_id=...`` next to each log line.
    """

    def filter(self, record) -> bool:
        record.trace_id = get_trace_id() or "-"
        return True
