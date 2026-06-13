from __future__ import annotations

# Re-export shim: these names live in cairn.shared.contracts and are
# surfaced here for the server's model package. They are intentionally
# unused locally (noqa: F401) — removing them breaks importers such as
# routers.settings and config.settings.
from cairn.shared.contracts import ReasoningType, Settings  # noqa: F401
