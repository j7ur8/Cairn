from __future__ import annotations

import urllib.error
import urllib.request
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from cairn.server.config_store import ConfigStore
from cairn.shared.config import DispatchConfig, merge_server_dispatch_data, validate_capability_resources, validate_role_resources
from cairn.shared.config.capability_models import prepare_capability_data
from cairn.shared.config.loader import load_server_data
from cairn.shared.config.role_models import prepare_role_data

_REPO_ROOT = Path(__file__).resolve().parents[4]
SERVER_YAML = Path("/cairn/server.yaml") if Path("/cairn/server.yaml").exists() else _REPO_ROOT / "server.yaml"
CONFIG_YAML = Path("/cairn/config.yaml") if Path("/cairn/config.yaml").exists() else _REPO_ROOT / "config.yaml"
CONFIG_RESOURCES_YAML = (
    Path("/cairn/config.resources.yaml")
    if Path("/cairn/config.resources.yaml").exists()
    else _REPO_ROOT / "config.resources.yaml"
)


def config_yaml_path() -> Path:
    return CONFIG_YAML


def server_yaml_path() -> Path:
    return SERVER_YAML


def resources_yaml_path() -> Path:
    return CONFIG_RESOURCES_YAML


def config_store() -> ConfigStore:
    return ConfigStore(
        dispatch_path=config_yaml_path(),
        resources_path=resources_yaml_path(),
    )


def utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_dispatch_data() -> dict[str, Any]:
    return config_store().load_dispatch()


def load_server_config_data() -> dict[str, Any]:
    return ConfigStore._read_yaml(server_yaml_path())


def load_resources_data() -> dict[str, Any]:
    return config_store().load_resources()


def save_dispatch_data(data: dict[str, Any], *, reload_dispatcher: bool = True) -> dict[str, Any]:
    workers = (data.get("worker_pool") or {}).get("workers") if isinstance(data.get("worker_pool"), dict) else []
    if not (workers or []):
        _atomic_write_yaml(config_yaml_path(), data)
        _reset_runtime_config()
        return _save_status(reload_applied=False, reload_error=None)
    _validate_dispatch_data(data)
    config_store().save_dispatch(data)
    reload_status = _save_status(reload_applied=False, reload_error=None)
    if reload_dispatcher:
        reload_status = trigger_dispatcher_reload()
    _reset_runtime_config()
    return reload_status


def save_resources_data(data: dict[str, Any], *, reload_dispatcher: bool = True) -> dict[str, Any]:
    merged = deepcopy(load_dispatch_data())
    merged["resources"] = data
    if ((merged.get("worker_pool") or {}).get("workers") or []):
        _validate_dispatch_data(merged)
    config_store().save_resources(data)
    reload_status = _save_status(reload_applied=False, reload_error=None)
    if reload_dispatcher:
        reload_status = trigger_dispatcher_reload()
    _reset_runtime_config()
    return reload_status


def _reset_runtime_config() -> None:
    from cairn.server.runtime_config import reset_runtime_config_cache

    reset_runtime_config_cache()


def trigger_dispatcher_reload() -> dict[str, Any]:
    from cairn.server.runtime_config import system_config
    runtime = system_config()
    if not runtime.dispatcher.reload_enabled:
        return _save_status(reload_applied=False, reload_error=None)
    token = runtime.auth.dispatcher_api_token
    req = urllib.request.Request(runtime.dispatcher.reload_url, method="POST")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read().decode("utf-8", errors="replace")
            if response.status >= 400:
                return _save_status(reload_applied=False, reload_error=f"dispatcher reload failed: HTTP {response.status}: {raw[:1000]}")
            try:
                payload = json.loads(raw or "{}")
            except json.JSONDecodeError as exc:
                return _save_status(reload_applied=False, reload_error=f"dispatcher reload invalid response: {exc}")
            if isinstance(payload, dict) and payload.get("ok") is True:
                return _save_status(reload_applied=True, reload_error=None)
            error = payload.get("error") if isinstance(payload, dict) else None
            return _save_status(reload_applied=False, reload_error=str(error or "dispatcher reload returned ok=false"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        return _save_status(reload_applied=False, reload_error=f"dispatcher reload failed: HTTP {exc.code}: {detail}")
    except Exception as exc:  # noqa: BLE001
        return _save_status(reload_applied=False, reload_error=f"dispatcher reload failed: {exc}")


def _save_status(*, reload_applied: bool, reload_error: str | None) -> dict[str, Any]:
    return {
        "saved": True,
        "reload_applied": reload_applied,
        "reload_error": reload_error,
    }


def config_revision() -> dict[str, str]:
    return {
        "server_sha256": _sha256(server_yaml_path()),
        "dispatch_sha256": _sha256(config_yaml_path()),
        "resources_sha256": _sha256(resources_yaml_path()),
    }


def _read_yaml(path: Path) -> dict[str, Any]:
    return ConfigStore._read_yaml(path)


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    ConfigStore._write_yaml(path, data)


def _overwrite_yaml(path: Path, text: str) -> None:
    ConfigStore._overwrite_text(path, text)


def _validate_dispatch_data(data: dict[str, Any]) -> None:
    server_payload, dispatch_payload, resources_raw = _dispatch_validation_data(data)
    resources_payload = prepare_capability_data(resources_raw, resources_yaml_path().parent)
    resources_payload = prepare_role_data(resources_payload, resources_yaml_path().parent)
    payload = merge_server_dispatch_data(server_payload, dispatch_payload)
    payload["resources"] = resources_payload
    try:
        config = DispatchConfig.model_validate(payload)
        validate_capability_resources(config)
        validate_role_resources(config)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"invalid dispatch config: {exc}") from exc


def _dispatch_validation_data(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    cleaned = deepcopy(data)
    resources = cleaned.pop("resources", None)
    if resources is None:
        resources = load_resources_data()
    server_data = load_server_data(config_yaml_path())
    worker_pool_raw = cleaned.get("worker_pool")
    worker_pool = worker_pool_raw if isinstance(worker_pool_raw, dict) else {}
    for worker in worker_pool.get("workers") or []:
        if not isinstance(worker, dict):
            continue
        for key in (
            "display_name",
            "description",
            "available",
            "detail",
            "healthcheck_timeout",
            "last_health_ok",
            "last_health_message",
            "last_health_at",
            "created_at",
            "updated_at",
        ):
            worker.pop(key, None)
    return server_data, cleaned, resources


def _sha256(path: Path) -> str:
    import hashlib

    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
