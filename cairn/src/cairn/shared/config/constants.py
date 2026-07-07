from __future__ import annotations

from typing import Literal

from cairn.shared.task_types import TASK_TYPE_REGISTRY, is_known_task_type


def _check_known_task_types(value: list[str]) -> list[str]:
    """Reject task types not present in the runtime registry."""
    unknown = [item for item in value if not is_known_task_type(item)]
    if unknown:
        raise ValueError(
            f"unknown task_types: {unknown!r}; "
            f"known: {', '.join(TASK_TYPE_REGISTRY.names())}"
        )
    return value


TaskType = str
WorkerType = Literal["claudecode", "codex", "mock"]
ContainerInactiveAction = Literal["remove", "stop"]
ReasoningEffort = Literal["low", "medium", "high", "xhigh"]

WORKER_ENV_KEYS: dict[WorkerType, tuple[str, ...]] = {
    "claudecode": (
        "ANTHROPIC_MODEL",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
    ),
    "codex": (
        "CODEX_MODEL",
        "CODEX_BASE_URL",
        "OPENAI_API_KEY",
    ),
    "mock": (),
}

DEFAULT_PROMPT_REQUIRED_TOKENS: dict[str, tuple[str, ...]] = {
    "reason.md": (
        "{hints}",
        "{fact_view}",
        "{full_graph}",
        "{fact_ids}",
        "{open_intents}",
        "{max_intents}",
    ),
    "explore.md": (
        "{hints}",
        "{fact_view}",
        "{full_graph}",
        "{intent_id}",
        "{intent_description}",
    ),
    "explore_conclude.md": ("{hints}", "{fact_view}", "{full_graph}", "{intent_id}", "{intent_description}"),
    "bootstrap.md": ("{hints}",),
    "bootstrap_conclude.md": ("{hints}",),
}

PROMPT_REQUIRED_TOKENS_BY_GROUP: dict[str, dict[str, tuple[str, ...]]] = {
    "mock": {
        "reason.md": ("{fact_ids}", "{open_intents}", "{max_intents}"),
        "explore.md": ("{intent_id}",),
        "explore_conclude.md": ("{intent_id}",),
        "bootstrap.md": ("{origin}", "{goal}", "{hints}"),
        "bootstrap_conclude.md": ("{origin}", "{goal}", "{hints}"),
    }
}
