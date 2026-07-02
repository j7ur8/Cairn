from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent

SNAKE_NAME_RE = re.compile(r"^_?[a-z][a-z0-9_]*$")
KEBAB_JS_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.js$")

PYTHON_ROOTS = [
    PROJECT_ROOT / "src" / "cairn",
    PROJECT_ROOT / "tests",
    PROJECT_ROOT / "migrations",
]

JS_ROOT = PROJECT_ROOT / "src" / "cairn" / "server" / "static" / "js"

EXPECTED_FILES = [
    PROJECT_ROOT / "src" / "cairn" / "server" / "schemas" / "__init__.py",
    PROJECT_ROOT / "src" / "cairn" / "server" / "application" / "project_queries.py",
    PROJECT_ROOT / "src" / "cairn" / "dispatcher" / "workers" / "adapters" / "claude_code.py",
    JS_ROOT / "workspace" / "state-projects.js",
    JS_ROOT / "workspace" / "state-graph.js",
    JS_ROOT / "workspace" / "state-llm-log.js",
    JS_ROOT / "workspace" / "state-ui.js",
    JS_ROOT / "app" / "state-ai-profiles.js",
    JS_ROOT / "app" / "state-settings-admin.js",
    REPO_ROOT / "config.mock.yaml",
    REPO_ROOT / "server.mock.yaml",
]

REMOVED_FILES = [
    JS_ROOT / "workspace" / "state.projects.js",
    JS_ROOT / "workspace" / "state.graph.js",
    JS_ROOT / "workspace" / "state.llm_log.js",
    JS_ROOT / "workspace" / "state.ui.js",
    JS_ROOT / "app" / "state.ai_profiles.js",
    JS_ROOT / "app" / "state.settings_admin.js",
    REPO_ROOT / "config_mock.yaml",
    REPO_ROOT / "server_mock.yaml",
]

JS_FILENAME_EXCEPTIONS = {
    "tailwind.config.js",
}

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


def _is_skipped(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def _is_vendor_capability_asset(path: Path) -> bool:
    try:
        parts = path.relative_to(REPO_ROOT).parts
    except ValueError:
        return False
    if not parts or parts[0] != "capabilities":
        return False
    return any(
        part == "tools" and index + 1 < len(parts) and parts[index + 1] == "vendor"
        for index, part in enumerate(parts[:-1])
    )


def _is_alembic_revision(path: Path) -> bool:
    return path.parent.name == "versions" and path.parent.parent.name == "migrations"


def _check_expected_files(errors: list[str]) -> None:
    for path in EXPECTED_FILES:
        if not path.exists():
            errors.append(f"missing canonical file: {path.relative_to(REPO_ROOT)}")
    for path in REMOVED_FILES:
        if path.exists():
            errors.append(f"legacy renamed file still exists: {path.relative_to(REPO_ROOT)}")


def _check_python_names(errors: list[str]) -> None:
    for root in PYTHON_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if _is_skipped(path) or _is_alembic_revision(path):
                continue
            stem = path.stem
            if stem == "__init__":
                continue
            if not SNAKE_NAME_RE.match(stem):
                errors.append(f"python module must be snake_case: {path.relative_to(REPO_ROOT)}")

        for path in root.rglob("*"):
            if not path.is_dir() or _is_skipped(path):
                continue
            if not (path / "__init__.py").exists():
                continue
            name = path.name
            if name == "versions":
                continue
            if not SNAKE_NAME_RE.match(name):
                errors.append(f"python package directory must be snake_case: {path.relative_to(REPO_ROOT)}")


def _check_js_names(errors: list[str]) -> None:
    if not JS_ROOT.exists():
        return
    for path in JS_ROOT.rglob("*.js"):
        if _is_skipped(path) or "vendor" in path.parts:
            continue
        name = path.name
        if name in JS_FILENAME_EXCEPTIONS:
            continue
        if not KEBAB_JS_RE.match(name):
            errors.append(f"first-party JS file must be kebab-case: {path.relative_to(REPO_ROOT)}")


def _check_yaml_names(errors: list[str]) -> None:
    for path in REPO_ROOT.rglob("*"):
        if _is_skipped(path) or not path.is_file():
            continue
        if path.suffix not in {".yaml", ".yml"}:
            continue
        if _is_vendor_capability_asset(path):
            continue
        if "_" in path.name:
            errors.append(f"YAML file name must not use underscores: {path.relative_to(REPO_ROOT)}")


def main() -> int:
    errors: list[str] = []
    _check_expected_files(errors)
    _check_python_names(errors)
    _check_js_names(errors)
    _check_yaml_names(errors)
    if errors:
        print("Naming check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Naming check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
