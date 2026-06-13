from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from cairn.shared.config import DispatcherConfig, ServerConfig, SystemConfig

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
    server = data.get("server")
    dispatcher = data.get("dispatcher")
    if not isinstance(server, dict):
        raise RuntimeError(f"dispatch.yaml missing required server section: {path}")
    if not isinstance(dispatcher, dict):
        raise RuntimeError(f"dispatch.yaml missing required dispatcher section: {path}")
    return SystemConfig.from_sections(
        ServerConfig.model_validate(server),
        DispatcherConfig.model_validate(dispatcher),
    )


def reset_runtime_config_cache() -> None:
    system_config.cache_clear()
