"""AI profile env overlay, with a TTL cache.

The scheduler tick walks the project AI chain and asks "what env vars
should I inject into the worker container for this snapshot?". The
answer is a function of:

  * the snapshot itself (model, base_url, api_key_env, reasoning)
  * the worker's host env (whether the api_key_env resolves) or the
    cached secret from the AI selection sync
  * the project's proxy (if any)

The host env rarely changes mid-run and the proxy is project-stable,
so the result is cacheable for a short window. Without the cache the
scheduler would re-read the dispatcher env (or, worse, re-fetch the
profile secret) on every tick of every active project.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from cairn.server.models import ProjectAiProfileSnapshot, ProxyConfig


OVERLAY_TTL_SECONDS = 60.0


def compute_ai_overlay(
    snapshot: ProjectAiProfileSnapshot,
    *,
    cached_secret: str | None = None,
    env: dict[str, str] | None = None,
    proxy_config: ProxyConfig | None = None,
) -> dict[str, str]:
    """Translate a snapshot into the env-var overlay for the worker.

    Resolution order for the auth token:

    1. ``cached_secret`` (the value pulled from ``/ai-profiles/{id}/secret``
       at sync time). This is the source of truth once the dispatcher
       has populated the AI selection cache.
    2. The dispatch process environment via
       ``os.environ[snapshot_api_key_env]`` — fallback for profiles
       whose secret is empty (e.g. seeded profiles that ran the first
       sync before the env var was set).

    Either way the worker container only ever receives the value,
    never the env-var name.
    """
    overlay: dict[str, str] = {}
    if snapshot.snapshot_api_key_env:
        token: str | None = None
        if cached_secret:
            token = cached_secret
        if not token:
            env_source = env if env is not None else os.environ
            token = env_source.get(snapshot.snapshot_api_key_env)
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
    if proxy_config is not None:
        overlay.update(_proxy_config_to_env(proxy_config))
    return overlay


def _proxy_config_to_env(cfg: ProxyConfig) -> dict[str, str]:
    """Translate a :class:`ProxyConfig` into the env vars a worker
    container needs in order to route traffic through the proxy.

    Duplicate of the helper in ``scheduler/loop.py``; keeping the
    overlay module standalone avoids a circular import.
    """
    userpass = ""
    if cfg.username and cfg.password:
        userpass = f"{cfg.username}:{cfg.password}@"
    elif cfg.username:
        userpass = f"{cfg.username}@"
    no_proxy = "localhost,127.0.0.1,cairn-server,cairn"
    if cfg.type == "socks5":
        return {
            "ALL_PROXY": f"socks5://{userpass}{cfg.host}:{cfg.port}",
            "NO_PROXY": no_proxy,
        }
    return {
        "HTTP_PROXY": f"http://{userpass}{cfg.host}:{cfg.port}",
        "HTTPS_PROXY": f"http://{userpass}{cfg.host}:{cfg.port}",
        "NO_PROXY": no_proxy,
    }


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
    _store: dict[tuple[str, str, str], tuple[float, dict[str, str]]] = field(default_factory=dict)

    def get(self, project_id: str, snapshot: ProjectAiProfileSnapshot) -> dict[str, str] | None:
        key = (project_id, snapshot.profile_id, snapshot.snapshot_api_key_env)
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
        key = (project_id, snapshot.profile_id, snapshot.snapshot_api_key_env)
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
