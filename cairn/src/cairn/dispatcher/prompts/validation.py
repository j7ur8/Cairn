from __future__ import annotations

from importlib import resources

from cairn.shared.config.constants import DEFAULT_PROMPT_REQUIRED_TOKENS, PROMPT_REQUIRED_TOKENS_BY_GROUP

DEFAULT_PROMPT_GROUP = "default"


def validate_prompt_resources() -> None:
    prompt_group = DEFAULT_PROMPT_GROUP
    prompts_dir = resources.files("cairn.dispatcher.prompts")
    group_dir = prompts_dir.joinpath(prompt_group)
    if not group_dir.is_dir():
        raise ValueError(f"missing prompt group: {prompt_group}")
    required_tokens = PROMPT_REQUIRED_TOKENS_BY_GROUP.get(prompt_group, DEFAULT_PROMPT_REQUIRED_TOKENS)
    for name, tokens in required_tokens.items():
        try:
            content = group_dir.joinpath(name).read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ValueError(f"prompt group {prompt_group} missing resource: {name}") from exc
        missing = [token for token in tokens if token not in content]
        if missing:
            raise ValueError(
                f"prompt group {prompt_group} resource {name} missing placeholders: {', '.join(missing)}"
            )
