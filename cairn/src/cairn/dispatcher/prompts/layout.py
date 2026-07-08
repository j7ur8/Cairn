from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

PROMPT_PHASES = ("bootstrap", "explore", "reason")
PROMPT_CATEGORIES = ("common", "roles", "instruction")
COMMON_PROMPT_PATHS: dict[str, tuple[str, str]] = {
    "bootstrap.md": ("bootstrap", "bootstrap.md"),
    "bootstrap_conclude.md": ("bootstrap", "bootstrap_conclude.md"),
    "bootstrap/FILE_OUTPUTS.md": ("bootstrap", "FILE_OUTPUTS.md"),
    "explore.md": ("explore", "explore.md"),
    "explore_conclude.md": ("explore", "explore_conclude.md"),
    "explore/FILE_OUTPUTS.md": ("explore", "FILE_OUTPUTS.md"),
    "reason.md": ("reason", "reason.md"),
    "reason/FILE_OUTPUTS.md": ("reason", "FILE_OUTPUTS.md"),
}
COMMON_PROMPT_NAMES = tuple(COMMON_PROMPT_PATHS)
EXECUTION_PROMPT_NAMES = (
    "bootstrap.md",
    "bootstrap_conclude.md",
    "explore.md",
    "explore_conclude.md",
    "reason.md",
)
INSTRUCTION_TEMPLATE_PATHS = ("Instruction.md", "AGENTS.md", "CLAUDE.md")


def prompts_root() -> Traversable:
    return resources.files("cairn.dispatcher.prompts")


def prompt_package_path() -> Path:
    import cairn.dispatcher.prompts as prompt_package

    package_paths = list(getattr(prompt_package, "__path__", []))
    if len(package_paths) != 1:
        raise RuntimeError("prompt resources are not writable files")
    return Path(package_paths[0]).resolve()


def validate_phase(phase: str) -> str:
    if phase not in PROMPT_PHASES:
        raise ValueError("invalid prompt phase")
    return phase


def validate_category(category: str) -> str:
    if category not in PROMPT_CATEGORIES:
        raise ValueError("invalid prompt category")
    return category


def common_prompt_traversable(name: str, root: Traversable | None = None) -> Traversable:
    phase, filename = COMMON_PROMPT_PATHS[name]
    base = root if root is not None else prompts_root()
    return base.joinpath(phase).joinpath("common").joinpath(filename)


def common_prompt_path(name: str, root: Path | None = None) -> Path:
    phase, filename = COMMON_PROMPT_PATHS[name]
    base = root if root is not None else prompt_package_path()
    return (base / phase / "common" / filename).resolve()


def role_prompt_path(phase: str, role_id: str, root: Path | None = None) -> Path:
    phase = validate_phase(phase)
    base = root if root is not None else prompt_package_path()
    return (base / phase / "roles" / f"{role_id}.md").resolve()


def instruction_prompt_path(phase: str, name: str = "Instruction.md", root: Path | None = None) -> Path:
    phase = validate_phase(phase)
    if name not in INSTRUCTION_TEMPLATE_PATHS:
        raise ValueError("invalid instruction template path")
    base = root if root is not None else prompt_package_path()
    return (base / phase / "instruction" / name).resolve()


def phase_for_logical_prompt(name: str) -> str:
    return COMMON_PROMPT_PATHS[name][0]


def file_outputs_prompt_name(phase: str) -> str:
    phase = validate_phase(phase)
    return f"{phase}/FILE_OUTPUTS.md"
