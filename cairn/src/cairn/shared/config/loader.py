from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from cairn.shared.config.capability_models import prepare_capability_data
from cairn.shared.config.role_models import prepare_role_data
from cairn.shared.config.worker_models import prepare_bind_mount_data

if TYPE_CHECKING:
    from cairn.shared.config.root import DispatchConfig


def load_dispatch_config(path: Path) -> DispatchConfig:
    from cairn.shared.config.root import DispatchConfig

    data = _read_yaml(path, label="dispatch config")
    resources_path = path.with_name("dispatch.resources.yaml")
    resources_data = _read_yaml(resources_path, label="resources config")
    data = prepare_bind_mount_data(data, path.parent)
    resources_data = prepare_capability_data(resources_data, resources_path.parent)
    resources_data = prepare_role_data(resources_data, resources_path.parent)
    payload = dict(data)
    payload["resources"] = resources_data
    config = DispatchConfig.model_validate(payload)
    validate_capability_resources(config)
    validate_role_resources(config)
    return config


def _read_yaml(path: Path, *, label: str) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a mapping: {path}")
    return data


def validate_capability_resources(config: DispatchConfig) -> None:
    for mcp in config.capabilities.mcp_servers:
        if not mcp.source_path:
            continue
        path = Path(mcp.source_path)
        if not path.exists():
            raise ValueError(f"capability mcp_server {mcp.id} source_path does not exist: {path}")
        if not path.is_dir():
            raise ValueError(f"capability mcp_server {mcp.id} source_path must be a directory: {path}")
    for skill in config.capabilities.skills:
        path = Path(skill.source_path)
        if not path.exists():
            raise ValueError(f"capability skill {skill.id} source_path does not exist: {path}")
        if not path.is_dir():
            raise ValueError(f"capability skill {skill.id} source_path must be a directory: {path}")


def validate_role_resources(config: DispatchConfig) -> None:
    for role in config.roles:
        if role.source_path is None:
            continue
        path = Path(role.source_path)
        if not path.exists():
            raise ValueError(f"role {role.id} source_path does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"role {role.id} source_path must be a file: {path}")
