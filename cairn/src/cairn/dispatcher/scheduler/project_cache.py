"""Per-project caches used by the scheduler loop.

Three pieces of dispatcher state used to live as raw ``dict`` fields
on :class:`cairn.dispatcher.scheduler.loop.DispatcherLoop`:

* ``_project_proxy_cache`` — resolved :class:`ProxyConfig` per project.
* ``_project_ai_cache`` — ordered AI profile chains per project / task.
* ``_project_ai_secret_cache`` — fetched ``sk`` values per profile.

They share a lifecycle (refreshed on every dispatch pass, invalidated
on proxy / AI selection changes) and are read by both the dispatch
pass and the per-task overlay builder. Pulling them into a small
class:

* makes the invalidation contract explicit (single ``invalidate`` /
  ``clear_all`` entrypoint);
* lets the loop import a typed handle instead of three untyped dicts;
* keeps the loop file focused on orchestration rather than cache
  bookkeeping.

The cache stores plain dicts so the existing call sites
(``self._project_ai_cache.get(project_id) or {}``) keep working -
:meth:`proxy`, :meth:`ai_chains`, :meth:`ai_secret` return the
underlying dicts directly.
"""
from __future__ import annotations

from typing import Any

from cairn.shared.protocol_models import ProjectAiProfileSnapshot
from cairn.shared.protocol_models import ProxyConfig


class ProjectCaches:
    """Bundle of per-project dispatcher caches.

    Each cache is a ``dict`` keyed by ``project_id`` (or
    ``(project_id, profile_id)`` for the secret cache) holding the
    last value seen during a dispatch pass. Missing keys fall back to
    a per-method default (``None`` for the proxy cache, empty dict
    for the AI chain cache) so callers can use ``or {}`` / ``or None``
    without explicit ``if key in cache`` checks.
    """

    __slots__ = ("proxy", "ai_chains", "ai_secret")

    def __init__(self) -> None:
        # project_id -> ProxyConfig | None
        self.proxy: dict[str, ProxyConfig | None] = {}
        # project_id -> dict[task_type, list[ProjectAiProfileSnapshot]] | None
        self.ai_chains: dict[str, dict[str, list[ProjectAiProfileSnapshot]] | None] = {}
        # project_id -> dict[profile_id, str | None]
        self.ai_secret: dict[str, dict[str, str | None]] = {}

    def invalidate(self, project_id: str) -> None:
        """Drop every cached value for ``project_id``."""
        self.proxy.pop(project_id, None)
        self.ai_chains.pop(project_id, None)
        self.ai_secret.pop(project_id, None)

    def clear_all(self) -> None:
        """Drop every cached value. Used on leader step-down so a
        re-acquired leader does not serve stale state from the
        previous lock window.
        """
        self.proxy.clear()
        self.ai_chains.clear()
        self.ai_secret.clear()

    # --- typed accessors ---------------------------------------------
    # These are convenience helpers that keep callers off the raw
    # dicts. The ``get`` variants never raise ``KeyError``; they
    # return the documented empty default.

    def get_proxy(self, project_id: str) -> ProxyConfig | None:
        return self.proxy.get(project_id)

    def set_proxy(self, project_id: str, value: ProxyConfig | None) -> None:
        self.proxy[project_id] = value

    def get_ai_chains(
        self, project_id: str
    ) -> dict[str, list[ProjectAiProfileSnapshot]] | None:
        return self.ai_chains.get(project_id)

    def set_ai_chains(
        self,
        project_id: str,
        chains: dict[str, list[ProjectAiProfileSnapshot]] | None,
    ) -> None:
        self.ai_chains[project_id] = chains

    def get_ai_secret(self, project_id: str) -> dict[str, str | None]:
        return self.ai_secret.get(project_id) or {}

    def set_ai_secret(
        self, project_id: str, secrets: dict[str, str | None]
    ) -> None:
        self.ai_secret[project_id] = secrets


__all__ = ["ProjectCaches"]
