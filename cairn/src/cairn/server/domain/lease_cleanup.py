from __future__ import annotations

from datetime import timedelta

from cairn.server.domain.time import parse_utc, utcnow


def lease_cutoff(timeout_seconds: int, now: str | None = None) -> str:
    current = now or utcnow()
    return (parse_utc(current) - timedelta(seconds=timeout_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
