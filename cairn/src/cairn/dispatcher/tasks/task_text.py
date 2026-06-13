from __future__ import annotations

LOG_PREVIEW_LIMIT = 1200
GRAPH_SNAPSHOT_ROOT = "/tmp/cairn-prompts"


def preview(text: str, limit: int = LOG_PREVIEW_LIMIT) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."
