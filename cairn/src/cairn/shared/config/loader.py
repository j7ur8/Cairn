from __future__ import annotations

import importlib
import os
import re
from pathlib import Path
from posixpath import join as posix_join
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
    data = normalize_server_config_data(data, server_path.parent)
    return prepare_bind_mount_data(data, server_path.parent)


def normalize_server_config_data(data: dict[str, Any], config_dir: Path) -> dict[str, Any]:
    _validate_new_server_schema(data)

    app = _mapping(data.get("app"), "app")
    database = _mapping(data.get("database"), "database")
    security = _mapping(data.get("security"), "security")
    admin = _mapping(data.get("admin"), "admin")
    storage = _mapping(data.get("storage"), "storage")
    worker = _mapping(data.get("worker"), "worker")
    dispatcher = _mapping(data.get("dispatcher"), "dispatcher")
    _validate_new_server_sections(app, database, security, admin, dispatcher, storage, worker)

    host_root = _resolve_host_path(config_dir, _required_text(storage, "host_root"))
    server_mount = _required_text(storage, "server_mount").rstrip("/")
    worker_workspace = _required_text(storage, "worker_workspace").rstrip("/")

    server_section: dict[str, Any] = {
        "base_url": _required_text(app, "public_url"),
        "database": database,
        "auth": security,
        "initial_admin": admin,
        "paths": {
            "datas_root": server_mount,
            "host_datas_root": host_root,
            "attachments_root": posix_join(server_mount, "attachments"),
            "project_files_root": posix_join(server_mount, "project-files"),
            "worker_attachments_root": posix_join(worker_workspace, "attachments"),
        },
    }
    if "log" in app:
        server_section["log"] = app["log"]
    if "retention" in app:
        server_section["retention"] = app["retention"]
    if "settings" in app:
        server_section["settings"] = app["settings"]

    dispatcher_section: dict[str, Any] = {}
    if "health_addr" in dispatcher:
        dispatcher_section["health_addr"] = dispatcher["health_addr"]
    dispatcher_section["reload"] = {
        "url": dispatcher.get("reload_url", "http://cairn-dispatcher:9100/reload"),
        "enabled": dispatcher.get("reload_enabled", True),
    }

    container: dict[str, Any] = {
        "image": _required_text(worker, "image"),
        "user": worker.get("container_user"),
        "exec_user": worker.get("exec_user"),
        "network_mode": _required_text(worker, "network"),
        "completed_action": _required_text(worker, "completed_action"),
        "stopped_action": worker.get("stopped_action", "stop"),
        "cap_add": worker.get("cap_add") or [],
        "bind_mounts": [
            {
                "name": "ctf-attachments",
                "host_path": str(Path(host_root) / "attachments"),
                "container_path": posix_join(worker_workspace, "attachments"),
                "read_only": True,
            },
            {
                "name": "project-files",
                "host_path": str(Path(host_root) / "project-files" / "{project_id}"),
                "container_path": worker_workspace,
                "read_only": False,
            },
        ],
    }
    for mount in worker.get("extra_mounts") or []:
        container["bind_mounts"].append(mount)
    resources = worker.get("resources") if isinstance(worker.get("resources"), dict) else {}
    for key in ("mem_limit", "pids_limit", "nano_cpus"):
        if key in resources:
            container[key] = resources[key]

    for key, value in list(container.items()):
        if value is None:
            container.pop(key)

    return {
        "server": server_section,
        "dispatcher": dispatcher_section,
        "worker_runtime": {
            "container": container,
            "common_env": worker.get("common_env") or {},
        },
    }


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


_NEW_SERVER_TOP_LEVEL_KEYS = {
    "app",
    "database",
    "security",
    "admin",
    "dispatcher",
    "storage",
    "worker",
}


def _validate_new_server_schema(data: dict[str, Any]) -> None:
    legacy_keys = sorted(key for key in ("server", "worker_runtime") if key in data)
    if legacy_keys:
        raise ValueError(
            "server config uses removed legacy top-level section(s): "
            f"{', '.join(legacy_keys)}. "
            "server.yaml must use app/database/security/admin/dispatcher/storage/worker."
        )
    missing = sorted(_NEW_SERVER_TOP_LEVEL_KEYS - set(data))
    if missing:
        raise ValueError(
            "server config missing required top-level section(s): "
            f"{', '.join(missing)}. "
            "server.yaml must use app/database/security/admin/dispatcher/storage/worker."
        )
    unknown = sorted(set(data) - _NEW_SERVER_TOP_LEVEL_KEYS)
    if unknown:
        raise ValueError(f"server config has unknown top-level section(s): {', '.join(unknown)}")


def _validate_new_server_sections(
    app: dict[str, Any],
    database: dict[str, Any],
    security: dict[str, Any],
    admin: dict[str, Any],
    dispatcher: dict[str, Any],
    storage: dict[str, Any],
    worker: dict[str, Any],
) -> None:
    _reject_unknown_keys("app", app, {"public_url", "log", "retention", "settings"})
    _reject_unknown_keys("database", database, {"url", "pool_size", "max_overflow", "pool_timeout"})
    _reject_unknown_keys("security", security, {"jwt_secret", "dispatcher_api_token"})
    _reject_unknown_keys("admin", admin, {"email", "password"})
    _reject_unknown_keys("dispatcher", dispatcher, {"health_addr", "reload_url", "reload_enabled"})
    _reject_unknown_keys("storage", storage, {"host_root", "server_mount", "worker_workspace"})
    _reject_unknown_keys(
        "worker",
        worker,
        {
            "image",
            "container_user",
            "exec_user",
            "network",
            "completed_action",
            "stopped_action",
            "cap_add",
            "extra_mounts",
            "resources",
            "common_env",
        },
    )
    resources = worker.get("resources")
    if isinstance(resources, dict):
        _reject_unknown_keys("worker.resources", resources, {"mem_limit", "pids_limit", "nano_cpus"})


def _reject_unknown_keys(label: str, section: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ValueError(f"server config {label} section has unknown field(s): {', '.join(unknown)}")


def _mapping(value: Any, label: str, *, required: bool = True) -> dict[str, Any]:
    if value is None and not required:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"server config {label} section must be a mapping")
    return value


def _required_text(section: dict[str, Any], key: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"server config missing required non-empty value: {key}")
    return value.strip()


_UNRESOLVED_ENV_RE = re.compile(r"\$(?:\{[^}]+\}|[A-Za-z_][A-Za-z0-9_]*)")


def _resolve_host_path(config_dir: Path, raw: str) -> str:
    expanded = os.path.expandvars(raw)
    unresolved = _UNRESOLVED_ENV_RE.search(expanded)
    if unresolved:
        raise ValueError(
            "server config storage.host_root contains unresolved environment variable "
            f"{unresolved.group(0)!r}; set it before loading server.yaml"
        )
    path = Path(os.path.expandvars(expanded)).expanduser()
    if not path.is_absolute():
        path = config_dir / path
    return str(path.resolve(strict=False))


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
