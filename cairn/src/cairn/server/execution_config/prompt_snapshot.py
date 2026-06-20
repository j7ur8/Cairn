from __future__ import annotations

import hashlib
import json
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any

from cairn.shared.config.constants import DEFAULT_PROMPT_REQUIRED_TOKENS, PROMPT_REQUIRED_TOKENS_BY_GROUP

DEFAULT_PROMPT_GROUP = "default"
PROMPT_SNAPSHOT_NAMES = (
    "bootstrap.md",
    "bootstrap_conclude.md",
    "explore.md",
    "explore_conclude.md",
    "reason.md",
)
PROMPT_GROUP_REQUIRED_RESOURCE_NAMES = PROMPT_SNAPSHOT_NAMES + ("FILE_OUTPUTS.md",)


def list_prompt_markdown_names(group_dir: Traversable) -> list[str]:
    names: list[str] = []

    def visit(node: Traversable, prefix: str = "") -> None:
        for child in node.iterdir():
            if child.name.startswith("."):
                continue
            rel_name = f"{prefix}{child.name}"
            if child.is_dir():
                visit(child, f"{rel_name}/")
            elif child.is_file() and child.name.endswith(".md"):
                names.append(rel_name)

    visit(group_dir)
    return _sort_prompt_names(names)


def _sort_prompt_names(names: list[str]) -> list[str]:
    core_order = {name: index for index, name in enumerate(PROMPT_SNAPSHOT_NAMES)}
    return sorted(names, key=lambda name: (0, core_order[name]) if name in core_order else (1, name))


def load_prompt_snapshot() -> dict[str, Any]:
    prompt_group = DEFAULT_PROMPT_GROUP
    prompts_dir = resources.files("cairn.dispatcher.prompts")
    group_dir = prompts_dir.joinpath(prompt_group)
    if not group_dir.is_dir():
        raise ValueError(f"missing prompt group: {prompt_group}")

    required_tokens = PROMPT_REQUIRED_TOKENS_BY_GROUP.get(prompt_group, DEFAULT_PROMPT_REQUIRED_TOKENS)
    prompt_names = list_prompt_markdown_names(group_dir)
    missing_required = [name for name in required_tokens if name not in prompt_names]
    if missing_required:
        raise ValueError(f"prompt group {prompt_group} missing resource: {missing_required[0]}")

    prompts: dict[str, str] = {}
    prompt_sha256: dict[str, str] = {}
    for name in prompt_names:
        try:
            content = group_dir.joinpath(*name.split("/")).read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ValueError(f"prompt group {prompt_group} missing resource: {name}") from exc
        missing = [token for token in required_tokens.get(name, ()) if token not in content]
        if missing:
            raise ValueError(
                f"prompt group {prompt_group} resource {name} missing placeholders: {', '.join(missing)}"
            )
        prompts[name] = content
        prompt_sha256[name] = _sha256_text(content)

    prompts_sha256 = _sha256_json(
        {
            "prompt_group": prompt_group,
            "prompt_names": prompt_names,
            "prompt_sha256": prompt_sha256,
        }
    )
    return {
        "prompt_group": prompt_group,
        "prompt_names": prompt_names,
        "prompts": prompts,
        "prompt_sha256": prompt_sha256,
        "prompts_sha256": prompts_sha256,
    }


def is_complete_prompt_group_dir(group_dir: Traversable) -> bool:
    return group_dir.is_dir() and all(group_dir.joinpath(name).is_file() for name in PROMPT_GROUP_REQUIRED_RESOURCE_NAMES)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(payload)
