from __future__ import annotations

from cairn.shared.contracts import Intent

DEFAULT_INTENT_PRIORITY = 0.5


def intent_priority_score(intent: Intent) -> float:
    if intent.priority_score is None:
        return DEFAULT_INTENT_PRIORITY
    return intent.priority_score


def intent_priority_key(intent: Intent) -> tuple[float, str, str]:
    return (intent_priority_score(intent), intent.created_at, intent.id)
