from __future__ import annotations

from cairn.dispatcher.prompts.layout import common_prompt_traversable, prompts_root
from cairn.shared.config.constants import DEFAULT_PROMPT_REQUIRED_TOKENS, PROMPT_REQUIRED_TOKENS_BY_GROUP


def validate_prompt_resources() -> None:
    prompts_dir = prompts_root()
    required_tokens = PROMPT_REQUIRED_TOKENS_BY_GROUP.get("default", DEFAULT_PROMPT_REQUIRED_TOKENS)
    for name, tokens in required_tokens.items():
        try:
            content = common_prompt_traversable(name, prompts_dir).read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ValueError(f"prompt resources missing resource: {name}") from exc
        missing = [token for token in tokens if token not in content]
        if missing:
            raise ValueError(
                f"prompt resource {name} missing placeholders: {', '.join(missing)}"
            )
