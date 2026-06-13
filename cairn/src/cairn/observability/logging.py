"""Structured logging for the Cairn server and dispatcher.

Two formatters are bundled:

  * ``JsonFormatter`` — one JSON object per line, ready to ship to
    Loki / Elastic / Datadog without further processing.
  * ``HumanFormatter`` — the existing ``[time] LEVEL module message``
    text format, kept for local development.

The default format is text unless the caller passes ``fmt="json"``.
Both formats include the current
``trace_id`` so logs can be correlated across HTTP requests, the
dispatcher loop, and the worker container pipeline.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from cairn.observability.trace import TraceIdFilter

_DEFAULT_TEXT_FORMAT = "[%(asctime)s] %(levelname)s %(name)s trace_id=%(trace_id)s %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per record.

    Uses ``record.__dict__`` so any structured fields added via
    ``logger.info("...", extra={"foo": "bar"})`` are included.
    """

    # Standard ``LogRecord`` attributes that should not be echoed as
    # custom fields.
    _RESERVED = {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)
            ) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key in payload:
                continue
            if key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except TypeError:
                payload[key] = repr(value)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class HumanFormatter(logging.Formatter):
    """Compact text formatter that always shows the trace id."""

    def __init__(self) -> None:
        super().__init__(fmt=_DEFAULT_TEXT_FORMAT, datefmt=_DEFAULT_DATEFMT)


_configured = False


def configure_logging(
    level: str = "INFO",
    *,
    fmt: str | None = None,
    component: str = "cairn",
) -> None:
    """Install the root handler.

    ``fmt`` defaults to ``text``. The handler also installs a
    :class:`TraceIdFilter` so every record carries ``trace_id``.
    """
    global _configured
    if fmt is None:
        fmt = "text"
    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(HumanFormatter())
    handler.addFilter(TraceIdFilter())

    root = logging.getLogger()
    # Wipe any pre-existing handlers (uvicorn, etc.) so the configured
    # formatter is the one that actually fires.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Quiet noisy libraries.
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).info(
        "logging configured component=%s level=%s format=%s", component, level, fmt,
    )
