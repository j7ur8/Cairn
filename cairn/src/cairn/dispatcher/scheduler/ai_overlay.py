"""AI profile env overlay, with a TTL cache.

The scheduler tick walks the project AI chain and asks "what env vars
should I inject into the worker container for this snapshot?". The
answer is a function of:

  * the snapshot itself (model, base_url, api_key_env, reasoning)
  * the cached secret from the AI selection sync

The secret cache changes only when the server refreshes project execution
config, so the result is cacheable for a short window.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from cairn.shared.contracts import ProjectAiProfileSnapshot

OVERLAY_TTL_SECONDS = 60.0


def compute_ai_overlay(
    snapshot: ProjectAiProfileSnapshot,
    *,
    cached_secret: str | None = None,
) -> dict[str, str]:
    """Translate a snapshot into the env-var overlay for the worker.

    ``cached_secret`` is the value pulled from the server-side execution
    config cache. The worker container receives the value under the
    canonical runtime env var name.
    """
    overlay: dict[str, str] = {}
    if snapshot.snapshot_api_key_env:
        token: str | None = None
        if cached_secret:
            token = cached_secret
        elif snapshot.snapshot_api_key_value:
            token = snapshot.snapshot_api_key_value
        if token:
            overlay[snapshot.snapshot_api_key_env] = token
    if snapshot.snapshot_reasoning_type:
        overlay["CAIRN_MODEL_REASONING_EFFORT"] = snapshot.snapshot_reasoning_type
    if snapshot.snapshot_worker_type == "codex":
        overlay["CODEX_MODEL"] = snapshot.snapshot_model
        if snapshot.snapshot_base_url:
            overlay["CODEX_BASE_URL"] = snapshot.snapshot_base_url
        if snapshot.snapshot_provider:
            overlay["CODEX_PROVIDER"] = snapshot.snapshot_provider
    elif snapshot.snapshot_worker_type == "claudecode":
        overlay["ANTHROPIC_MODEL"] = snapshot.snapshot_model
        if snapshot.snapshot_base_url:
            overlay["ANTHROPIC_BASE_URL"] = snapshot.snapshot_base_url
        if snapshot.snapshot_provider:
            overlay["ANTHROPIC_PROVIDER"] = snapshot.snapshot_provider
    return overlay


@dataclass(slots=True)
class AIOverlayCache:
    """In-process TTL cache for ``compute_ai_overlay`` results.

    The cache key is ``(project_id, profile_id, api_key_env)`` so a
    profile update on disk invalidates the entry automatically once
    the TTL expires. The cache is intentionally tiny: a project with
    one primary + two fallbacks produces three entries, and the
    scheduler loop only iterates the active project set.
    """

    ttl_seconds: float = OVERLAY_TTL_SECONDS
    _store: dict[tuple[str, str, str, str, str], tuple[float, dict[str, str]]] = field(default_factory=dict)

    def get(self, project_id: str, snapshot: ProjectAiProfileSnapshot) -> dict[str, str] | None:
        key = self._key(project_id, snapshot)
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.time():
            self._store.pop(key, None)
            return None
        return value

    def put(
        self,
        project_id: str,
        snapshot: ProjectAiProfileSnapshot,
        overlay: dict[str, str],
    ) -> None:
        key = self._key(project_id, snapshot)
        self._store[key] = (time.time() + self.ttl_seconds, dict(overlay))

    def invalidate(self, project_id: str | None = None) -> None:
        """Drop cached entries.

        ``project_id=None`` clears everything; a specific project id
        only drops that project's entries. The scheduler calls this
        on profile sync (so the next tick rebuilds overlays for
        affected projects) and on project completion.
        """
        if project_id is None:
            self._store.clear()
            return
        for key in list(self._store):
            if key[0] == project_id:
                self._store.pop(key, None)

    def __len__(self) -> int:
        return len(self._store)

    @staticmethod
    def _key(project_id: str, snapshot: ProjectAiProfileSnapshot) -> tuple[str, str, str, str, str]:
        return (
            project_id,
            snapshot.profile_id,
            snapshot.snapshot_api_key_env,
            snapshot.snapshot_api_key_value,
            snapshot.snapshot_model,
        )
