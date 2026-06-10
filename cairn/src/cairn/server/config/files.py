from __future__ import annotations

import urllib.error
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException

from cairn.shared.dispatch_config import DispatchConfig
from cairn.server.config_store import ConfigStore


_REPO_ROOT = Path(__file__).resolve().parents[4]
DISPATCH_YAML = Path("/cairn/dispatch.yaml") if Path("/cairn/dispatch.yaml").exists() else _REPO_ROOT / "dispatch.yaml"
CAPABILITIES_YAML = (
    Path("/cairn/dispatch.capabilities.yaml")
    if Path("/cairn/dispatch.capabilities.yaml").exists()
    else _REPO_ROOT / "dispatch.capabilities.yaml"
)


def dispatch_yaml_path() -> Path:
    return DISPATCH_YAML


def capabilities_yaml_path() -> Path:
    return CAPABILITIES_YAML


def config_store() -> ConfigStore:
    return ConfigStore(
        dispatch_path=dispatch_yaml_path(),
        capabilities_path=capabilities_yaml_path(),
    )


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_dispatch_data() -> dict[str, Any]:
    return config_store().load_dispatch()


def load_capabilities_data() -> dict[str, Any]:
    return config_store().load_capabilities()


def save_dispatch_data(data: dict[str, Any], *, reload_dispatcher: bool = True) -> None:
    if not (data.get("workers") or []):
        _atomic_write_yaml(dispatch_yaml_path(), data)
        return
    _validate_dispatch_data(data)
    config_store().save_dispatch(data)
    if reload_dispatcher:
        trigger_dispatcher_reload()


def save_capabilities_data(data: dict[str, Any], *, reload_dispatcher: bool = True) -> None:
    merged = deepcopy(load_dispatch_data())
    for key in ("remote_support", "capabilities", "roles"):
        if key in data:
            merged[key] = data[key]
    if merged.get("workers") or []:
        _validate_dispatch_data(merged)
    config_store().save_capabilities(data)
    if reload_dispatcher:
        trigger_dispatcher_reload()


def trigger_dispatcher_reload() -> None:
    from cairn.server.runtime_config import system_config
    runtime = system_config()
    if not runtime.dispatcher.reload_enabled:
        return
    token = runtime.auth.dispatcher_api_token
    req = urllib.request.Request(runtime.dispatcher.reload_url, method="POST")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status >= 400:
                raise HTTPException(503, f"dispatcher reload failed: HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise HTTPException(503, f"dispatcher reload failed: HTTP {exc.code}: {detail}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"dispatcher reload failed: {exc}") from exc


def config_revision() -> dict[str, str]:
    return {
        "dispatch_sha256": _sha256(dispatch_yaml_path()),
        "capabilities_sha256": _sha256(capabilities_yaml_path()),
    }


def _read_yaml(path: Path) -> dict[str, Any]:
    return ConfigStore._read_yaml(path)


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    ConfigStore._write_yaml(path, data)


def _overwrite_yaml(path: Path, text: str) -> None:
    ConfigStore._overwrite_text(path, text)


def _validate_dispatch_data(data: dict[str, Any]) -> None:
    validation_data = _dispatch_validation_data(data)
    validation_path = dispatch_yaml_path().with_name("dispatch.validation.yaml")
    with validation_path.open("w", encoding="utf-8") as tmp:
        yaml.safe_dump(validation_data, tmp, sort_keys=False, allow_unicode=True)
    try:
        DispatchConfig.load(validation_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"invalid dispatch config: {exc}") from exc
    finally:
        validation_path.unlink(missing_ok=True)


def _dispatch_validation_data(data: dict[str, Any]) -> dict[str, Any]:
    cleaned = deepcopy(data)
    for worker in cleaned.get("workers") or []:
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
    cleaned.pop("server_settings", None)
    cleaned.pop("proxies", None)
    return cleaned


def _sha256(path: Path) -> str:
    import hashlib

    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
