from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import yaml

from cairn.shared.config.capability_models import prepare_capability_data
from cairn.shared.config.role_models import prepare_role_data
from cairn.shared.config.worker_models import prepare_bind_mount_data


class ConfigError(ValueError):
    """Raised when dispatch configuration cannot be loaded or validated.

    All config-load failures (missing/unreadable files, invalid YAML, schema
    validation, and resource-path checks) are funnelled through this type so the
    dispatcher entrypoint can fail fast with a single clear message instead of a
    bare traceback crash-loop.
    """


def server_config_path(dispatch_path: Path) -> Path:
    return dispatch_path.with_name("server.yaml")


def load_server_data(path: Path) -> dict[str, Any]:
    server_path = server_config_path(path)
    return load_server_file(server_path)


def load_server_file(server_path: Path) -> dict[str, Any]:
    data = _read_yaml(server_path, label="server config")
    return prepare_bind_mount_data(data, server_path.parent)


def merge_server_dispatch_data(server_data: dict[str, Any], dispatch_data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(dispatch_data)
    server_section = dict(server_data.get("server") or {})
    server_section.update(payload.get("server") or {})
    dispatcher_section = dict(server_data.get("dispatcher") or {})
    dispatcher_section.update(payload.get("dispatcher") or {})
    payload["server"] = server_section
    payload["dispatcher"] = dispatcher_section
    if "worker_runtime" in server_data:
        payload["worker_runtime"] = server_data["worker_runtime"]
    return payload


def load_dispatch_config(path: Path) -> Any:
    from pydantic import ValidationError

    try:
        data = _read_yaml(path, label="dispatch config")
        server_data = load_server_data(path)
        resources_path = path.with_name("config.resources.yaml")
        resources_data = _read_yaml(resources_path, label="resources config")
        data = merge_server_dispatch_data(server_data, data)
        resources_data = prepare_capability_data(resources_data, resources_path.parent)
        resources_data = prepare_role_data(resources_data, resources_path.parent)
        payload = dict(data)
        payload["resources"] = resources_data
        DispatchConfig = importlib.import_module("cairn.shared.config.root").DispatchConfig
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


def validate_capability_resources(config: Any) -> None:
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


def validate_role_resources(config: Any) -> None:
    for role in config.roles:
        if role.source_path is None:
            continue
        path = Path(role.source_path)
        if not path.exists():
            raise ConfigError(f"role {role.id} source_path does not exist: {path}")
        if not path.is_file():
            raise ConfigError(f"role {role.id} source_path must be a file: {path}")
