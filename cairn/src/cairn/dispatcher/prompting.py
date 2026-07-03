from __future__ import annotations

import json
import logging
from importlib import resources
from typing import Any

LOG = logging.getLogger(__name__)
DEFAULT_PROMPT_GROUP = "default"


def load_prompt(name: str) -> str:
    return resources.files("cairn.dispatcher.prompts").joinpath(DEFAULT_PROMPT_GROUP).joinpath(name).read_text(encoding="utf-8")


def load_prompt_from_execution_config(
    execution_config: dict | None,
    name: str,
    reporter: Any | None = None,
) -> str:
    prompt_snapshot = execution_config.get("prompt_snapshot") if isinstance(execution_config, dict) else None
    prompts = prompt_snapshot.get("prompts") if isinstance(prompt_snapshot, dict) else None
    if isinstance(prompts, dict):
        content = prompts.get(name)
        if isinstance(content, str):
            return content
    message = f"execution config prompt snapshot missing {name}; using default prompt template"
    LOG.warning(message)
    if reporter is not None:
        reporter.emit_error("prompt_snapshot", "warning", message)
    return load_prompt(name)


def render_prompt(template: str, replacements: dict[str, str]) -> str:
    text = template
    for key, value in replacements.items():
        text = text.replace("{" + key + "}", value)
    return text


def format_fact_ids(fact_ids: list[str]) -> str:
    return format_json_block(fact_ids)


def format_open_intents(intents: list[dict[str, Any]]) -> str:
    return format_json_block(intents)


def format_hints(hints: list[dict[str, Any]]) -> str:
    return format_json_block(hints)


def format_json_block(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
