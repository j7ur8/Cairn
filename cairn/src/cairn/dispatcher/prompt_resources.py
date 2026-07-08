from __future__ import annotations

from cairn.dispatcher.prompts.layout import common_prompt_traversable, file_outputs_prompt_name, prompts_root, validate_phase


def load_prompt_files_appendix(task_type: str) -> tuple[str, list[str]]:
    try:
        phase = validate_phase(task_type)
    except ValueError:
        return "", [f"files: invalid task family for FILE_OUTPUTS.md: {task_type}"]
    resource_name = file_outputs_prompt_name(phase)
    label = f"{phase}/common/FILE_OUTPUTS.md"
    try:
        text = common_prompt_traversable(resource_name, prompts_root()).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "", [f"files: prompt resources missing {label}"]
    except OSError as exc:
        return "", [f"files: prompt resources failed to read {label}: {exc}"]
    if not text:
        return "", [f"files: prompt resources {label} is empty"]
    return text, []
