from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(slots=True)
class BufferedOutput:
    phase: str
    stream: str
    content: str


class OutputBuffer:
    def __init__(self, flush_interval_ms: int, flush_max_bytes: int):
        self.flush_interval_seconds = flush_interval_ms / 1000
        self.flush_max_bytes = flush_max_bytes
        self._phase: str | None = None
        self._stream: str | None = None
        self._chunks: list[str] = []
        self._bytes = 0
        self._last_flush = time.monotonic()

    def add(self, phase: str, stream: str, chunk: str) -> list[BufferedOutput]:
        if not chunk:
            return []
        flushed: list[BufferedOutput] = []
        if self._chunks and (self._phase != phase or self._stream != stream):
            flushed.extend(self.flush())
        self._phase = phase
        self._stream = stream
        self._chunks.append(chunk)
        self._bytes += len(chunk.encode("utf-8"))
        now = time.monotonic()
        if self._bytes >= self.flush_max_bytes or now - self._last_flush >= self.flush_interval_seconds:
            flushed.extend(self.flush())
        return flushed

    def flush(self) -> list[BufferedOutput]:
        if not self._chunks or self._phase is None or self._stream is None:
            return []
        output = BufferedOutput(self._phase, self._stream, "".join(self._chunks))
        self._chunks = []
        self._bytes = 0
        self._last_flush = time.monotonic()
        return [output]
