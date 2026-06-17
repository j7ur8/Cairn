from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from cairn.shared.config import DispatcherConfig, ServerConfig, SystemConfig
from cairn.shared.config.loader import load_server_file, merge_server_dispatch_data

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DISPATCH_CONFIG_PATH = _REPO_ROOT / "config.yaml"
DEFAULT_SERVER_CONFIG_PATH = _REPO_ROOT / "server.yaml"


def dispatch_config_path() -> Path:
    container_path = Path("/cairn/config.yaml")
    if container_path.exists():
        return container_path
    return DEFAULT_DISPATCH_CONFIG_PATH


def server_config_path() -> Path:
    container_path = Path("/cairn/server.yaml")
    if container_path.exists():
        return container_path
    return DEFAULT_SERVER_CONFIG_PATH


@lru_cache(maxsize=1)
def system_config() -> SystemConfig:
    path = dispatch_config_path()
    server_path = server_config_path()
    dispatch_data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(dispatch_data, dict):
        raise RuntimeError(f"dispatch config must be a mapping: {path}")
    server_data = load_server_file(server_path)
    data = merge_server_dispatch_data(server_data, dispatch_data)
    server = data.get("server")
    dispatcher = data.get("dispatcher")
    if not isinstance(server, dict):
        raise RuntimeError(f"merged config missing required server section: {server_path} + {path}")
    if not isinstance(dispatcher, dict):
        raise RuntimeError(f"merged config missing required dispatcher section: {server_path} + {path}")
    return SystemConfig.from_sections(
        ServerConfig.model_validate(server),
        DispatcherConfig.model_validate(dispatcher),
    )


def reset_runtime_config_cache() -> None:
    system_config.cache_clear()
