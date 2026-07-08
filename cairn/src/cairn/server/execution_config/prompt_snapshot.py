from __future__ import annotations

import hashlib
import json
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any

from cairn.dispatcher.prompts.layout import COMMON_PROMPT_NAMES, EXECUTION_PROMPT_NAMES, common_prompt_traversable
from cairn.shared.config.constants import DEFAULT_PROMPT_REQUIRED_TOKENS, PROMPT_REQUIRED_TOKENS_BY_GROUP

PROMPT_SNAPSHOT_NAMES = EXECUTION_PROMPT_NAMES
PROMPT_REQUIRED_RESOURCE_NAMES = COMMON_PROMPT_NAMES


def list_prompt_markdown_names(root_dir: Traversable) -> list[str]:
    names: list[str] = []
    for name in EXECUTION_PROMPT_NAMES:
        if common_prompt_traversable(name, root_dir).is_file():
            names.append(name)
    return _sort_prompt_names(names)


def _sort_prompt_names(names: list[str]) -> list[str]:
    core_order = {name: index for index, name in enumerate(PROMPT_SNAPSHOT_NAMES)}
    return sorted(names, key=lambda name: (0, core_order[name]) if name in core_order else (1, name))


def load_prompt_snapshot() -> dict[str, Any]:
    prompts_dir = resources.files("cairn.dispatcher.prompts")

    required_tokens = PROMPT_REQUIRED_TOKENS_BY_GROUP.get("default", DEFAULT_PROMPT_REQUIRED_TOKENS)
    prompt_names = list_prompt_markdown_names(prompts_dir)
    missing_required = [name for name in required_tokens if name not in prompt_names]
    if missing_required:
        raise ValueError(f"prompt resources missing resource: {missing_required[0]}")

    prompts: dict[str, str] = {}
    prompt_sha256: dict[str, str] = {}
    for name in prompt_names:
        try:
            content = common_prompt_traversable(name, prompts_dir).read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ValueError(f"prompt resources missing resource: {name}") from exc
        missing = [token for token in required_tokens.get(name, ()) if token not in content]
        if missing:
            raise ValueError(
                f"prompt resource {name} missing placeholders: {', '.join(missing)}"
            )
        prompts[name] = content
        prompt_sha256[name] = _sha256_text(content)

    prompts_sha256 = _sha256_json(
        {
            "prompt_names": prompt_names,
            "prompt_sha256": prompt_sha256,
        }
    )
    return {
        "prompt_names": prompt_names,
        "prompts": prompts,
        "prompt_sha256": prompt_sha256,
        "prompts_sha256": prompts_sha256,
    }


def is_complete_prompt_group_dir(root_dir: Traversable) -> bool:
    return all(common_prompt_traversable(name, root_dir).is_file() for name in PROMPT_REQUIRED_RESOURCE_NAMES)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(payload)
