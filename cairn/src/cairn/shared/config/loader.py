from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from cairn.shared.config.capability_models import prepare_capability_data
from cairn.shared.config.role_models import prepare_role_data
from cairn.shared.config.worker_models import prepare_bind_mount_data

if TYPE_CHECKING:
    from cairn.shared.config.root import DispatchConfig


class ConfigError(ValueError):
    """Raised when dispatch configuration cannot be loaded or validated.

    All config-load failures (missing/unreadable files, invalid YAML, schema
    validation, and resource-path checks) are funnelled through this type so the
    dispatcher entrypoint can fail fast with a single clear message instead of a
    bare traceback crash-loop.
    """


def load_dispatch_config(path: Path) -> DispatchConfig:
    from pydantic import ValidationError

    from cairn.shared.config.root import DispatchConfig

    try:
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
    except ConfigError:
        raise
    except ValidationError as exc:
        raise ConfigError(f"dispatch config failed validation ({path}):\n{exc}") from exc
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    return config


def _read_yaml(path: Path, *, label: str) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"{label} not found: {path}")
    if path.is_dir():
        # A bind-mount whose host source path is missing makes the Docker daemon
        # auto-create an empty directory at the mount target. Surface that as an
        # actionable error instead of a bare IsADirectoryError crash-loop.
        raise ValueError(
            f"{label} is a directory, not a file: {path}. "
            "This usually means the bind-mount source file is missing on the host; "
            "ensure the file exists before starting the container."
        )
    if not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"{label} could not be read: {path} ({exc})") from exc
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{label} is not valid YAML: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a mapping: {path}")
    return data


def validate_capability_resources(config: DispatchConfig) -> None:
    for mcp in config.capabilities.mcp_servers:
        if not mcp.source_path:
            continue
        path = Path(mcp.source_path)
        if not path.exists():
            raise ConfigError(f"capability mcp_server {mcp.id} source_path does not exist: {path}")
        if not path.is_dir():
            raise ConfigError(f"capability mcp_server {mcp.id} source_path must be a directory: {path}")
    for skill in config.capabilities.skills:
        path = Path(skill.source_path)
        if not path.exists():
            raise ConfigError(f"capability skill {skill.id} source_path does not exist: {path}")
        if not path.is_dir():
            raise ConfigError(f"capability skill {skill.id} source_path must be a directory: {path}")


def validate_role_resources(config: DispatchConfig) -> None:
    for role in config.roles:
        if role.source_path is None:
            continue
        path = Path(role.source_path)
        if not path.exists():
            raise ConfigError(f"role {role.id} source_path does not exist: {path}")
        if not path.is_file():
            raise ConfigError(f"role {role.id} source_path must be a file: {path}")
