from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from cairn.shared.dispatch_config import SystemConfig


_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DISPATCH_CONFIG_PATH = _REPO_ROOT / "dispatch.yaml"


def dispatch_config_path() -> Path:
    container_path = Path("/cairn/dispatch.yaml")
    if container_path.exists():
        return container_path
    return DEFAULT_DISPATCH_CONFIG_PATH


@lru_cache(maxsize=1)
def system_config() -> SystemConfig:
    path = dispatch_config_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"dispatch config must be a mapping: {path}")
    system = data.get("system")
    if not isinstance(system, dict):
        raise RuntimeError(f"dispatch.yaml missing required system section: {path}")
    return SystemConfig.model_validate(system)


def reset_runtime_config_cache() -> None:
    system_config.cache_clear()
