from __future__ import annotations

from importlib import resources

DEFAULT_PROMPT_GROUP = "default"


def load_prompt_files_appendix() -> tuple[str, list[str]]:
    prompt_group = DEFAULT_PROMPT_GROUP
    try:
        text = (
            resources.files("cairn.dispatcher.prompts")
            .joinpath(prompt_group)
            .joinpath("FILE_OUTPUTS.md")
            .read_text(encoding="utf-8")
            .strip()
        )
    except FileNotFoundError:
        return "", [f"files: prompt group {prompt_group} missing FILE_OUTPUTS.md"]
    except OSError as exc:
        return "", [f"files: prompt group {prompt_group} failed to read FILE_OUTPUTS.md: {exc}"]
    if not text:
        return "", [f"files: prompt group {prompt_group} FILE_OUTPUTS.md is empty"]
    return text, []
