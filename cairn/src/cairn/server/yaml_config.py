from __future__ import annotations

import errno
import os
import re
import urllib.error
import urllib.request
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterator

import yaml
from fastapi import HTTPException

from cairn.dispatcher.config import DispatchConfig, WORKER_ENV_KEYS
from cairn.dispatcher.capabilities import catalog_payload as capability_catalog_payload
from cairn.dispatcher.roles import catalog_payload as role_catalog_payload
from cairn.server.models import (
    AiProfile,
    AiProfileCreate,
    AiProfileUpdate,
    CapabilityAdminRequest,
    CapabilityCatalogItem,
    RegisterRoleCatalogItem,
    ProxyConfig,
    ProxyCreate,
    ProxySummary,
    ProxyUpdate,
    RoleCatalogItem,
    Settings,
    auth_env_warning,
    canonical_auth_env,
)


_REPO_ROOT = Path(__file__).resolve().parents[4]
DISPATCH_YAML = Path(os.environ.get("CAIRN_DISPATCH_CONFIG_PATH", str(_REPO_ROOT / "dispatch.yaml")))
CAPABILITIES_YAML = Path(os.environ.get("CAIRN_CAPABILITIES_CONFIG_PATH", str(_REPO_ROOT / "dispatch.capabilities.yaml")))
_DISPATCHER_RELOAD_URL = os.environ.get("CAIRN_DISPATCHER_RELOAD_URL", "http://cairn-dispatcher:9100/reload")
os.environ.setdefault("CAIRN_DISPATCHER_DATAS_ROOT", str(_REPO_ROOT / "datas"))


def dispatch_yaml_path() -> Path:
    return Path(os.environ.get("CAIRN_DISPATCH_CONFIG_PATH", str(DISPATCH_YAML)))


def capabilities_yaml_path() -> Path:
    return Path(os.environ.get("CAIRN_CAPABILITIES_CONFIG_PATH", str(CAPABILITIES_YAML)))


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_dispatch_data() -> dict[str, Any]:
    return _read_yaml(dispatch_yaml_path())


def load_capabilities_data() -> dict[str, Any]:
    return _read_yaml(capabilities_yaml_path())


def save_dispatch_data(data: dict[str, Any], *, reload_dispatcher: bool = True) -> None:
    if not (data.get("workers") or []):
        _atomic_write_yaml(dispatch_yaml_path(), data)
        return
    _validate_dispatch_data(data)
    _atomic_write_yaml(dispatch_yaml_path(), data)
    if reload_dispatcher:
        trigger_dispatcher_reload()


def save_capabilities_data(data: dict[str, Any], *, reload_dispatcher: bool = True) -> None:
    merged = deepcopy(load_dispatch_data())
    for key in ("remote_support", "capabilities", "roles"):
        if key in data:
            merged[key] = data[key]
    if merged.get("workers") or []:
        _validate_dispatch_data(merged)
    _atomic_write_yaml(capabilities_yaml_path(), data)
    if reload_dispatcher:
        trigger_dispatcher_reload()


def trigger_dispatcher_reload() -> None:
    if os.environ.get("CAIRN_DISABLE_DISPATCHER_RELOAD") == "1":
        return
    token = os.environ.get("CAIRN_API_TOKEN", "")
    req = urllib.request.Request(_DISPATCHER_RELOAD_URL, method="POST")
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


def list_yaml_ai_profiles() -> list[AiProfile]:
    data = load_dispatch_data()
    profiles = [_worker_to_profile(worker) for worker in _workers(data)]
    profiles.sort(key=lambda item: item.name)
    return profiles


def get_yaml_ai_profile(profile_id: str) -> AiProfile:
    for profile in list_yaml_ai_profiles():
        if profile.id == profile_id:
            return profile
    raise HTTPException(404, f"ai profile not found: {profile_id}")


def create_yaml_ai_profile(body: AiProfileCreate) -> AiProfile:
    data = load_dispatch_data()
    workers = _workers(data)
    profile_id = _new_ai_id(body.name, workers)
    worker = _profile_body_to_worker(profile_id, body)
    workers.append(worker)
    save_dispatch_data(data)
    return _worker_to_profile(worker)


def update_yaml_ai_profile(profile_id: str, body: AiProfileUpdate) -> AiProfile:
    data = load_dispatch_data()
    workers = _workers(data)
    idx = _worker_index(workers, profile_id)
    if idx is None:
        raise HTTPException(404, f"ai profile not found: {profile_id}")
    profile = _worker_to_profile(workers[idx])
    values = profile.model_dump()
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "sk":
            continue
        if value is not None:
            values[key] = value
    if body.sk is not None:
        values["sk"] = body.sk
    else:
        values["sk"] = profile.sk
    values["id"] = profile_id
    workers[idx] = _profile_values_to_worker(values, existing=workers[idx])
    save_dispatch_data(data)
    return _worker_to_profile(workers[idx])


def delete_yaml_ai_profile(profile_id: str) -> None:
    data = load_dispatch_data()
    workers = _workers(data)
    idx = _worker_index(workers, profile_id)
    if idx is None:
        raise HTTPException(404, f"ai profile not found: {profile_id}")
    workers.pop(idx)
    save_dispatch_data(data, reload_dispatcher=bool(workers))


def yaml_ai_profile_secret(profile_id: str) -> str | None:
    profile = get_yaml_ai_profile(profile_id)
    value = profile.sk.strip()
    if not value:
        return None
    match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-[^}]*)?\}", value)
    if match:
        return os.environ.get(match.group(1)) or None
    if value == "cairn-placeholder":
        return None
    return value


def update_yaml_ai_profile_health(profile_id: str, *, ok: bool, message: str) -> None:
    data = load_dispatch_data()
    workers = _workers(data)
    idx = _worker_index(workers, profile_id)
    if idx is None:
        return
    workers[idx]["available"] = bool(ok)
    workers[idx]["last_health_ok"] = bool(ok)
    workers[idx]["last_health_message"] = message[:1000]
    workers[idx]["last_health_at"] = utcnow()
    save_dispatch_data(data, reload_dispatcher=False)


def update_yaml_ai_profile_models(profile_id: str, models: list[str]) -> None:
    data = load_dispatch_data()
    workers = _workers(data)
    idx = _worker_index(workers, profile_id)
    if idx is None:
        return
    profile = _worker_to_profile(workers[idx])
    cleaned = [item.strip() for item in models if item and item.strip()]
    workers[idx]["models"] = list(dict.fromkeys(cleaned))
    workers[idx]["updated_at"] = utcnow()
    save_dispatch_data(data, reload_dispatcher=False)


def sync_yaml_ai_profiles(workers_payload: list[Any]) -> list[AiProfile]:
    data = load_dispatch_data()
    existing_workers = _workers(data)
    manual_workers = [worker for worker in existing_workers if _is_manual_worker(worker)]
    existing_by_name = {str(worker.get("name") or ""): worker for worker in existing_workers}
    synced_workers: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for item in workers_payload:
        worker_type = str(getattr(item, "worker_type", "") or "")
        name = str(getattr(item, "name", "") or "").strip()
        model = str(getattr(item, "model", "") or "").strip()
        if worker_type not in ("codex", "claudecode") or not name or not model:
            continue
        if name in seen_names:
            continue
        seen_names.add(name)
        synced_workers.append(_sync_worker_to_yaml_worker(item, existing=existing_by_name.get(name)))
    data["workers"] = manual_workers + synced_workers
    save_dispatch_data(data, reload_dispatcher=False)
    return list_yaml_ai_profiles()


def list_yaml_proxies() -> list[ProxySummary]:
    data = load_dispatch_data()
    proxies = [_proxy_to_config(item) for item in _proxies(data)]
    proxies.sort(key=lambda item: (item.created_at, item.id), reverse=True)
    return [_proxy_summary(item) for item in proxies]


def get_yaml_proxy(proxy_id: str) -> ProxyConfig:
    data = load_dispatch_data()
    for item in _proxies(data):
        if item.get("id") == proxy_id:
            return _proxy_to_config(item)
    raise HTTPException(404, f"proxy not found: {proxy_id}")


def create_yaml_proxy(body: ProxyCreate) -> ProxyConfig:
    data = load_dispatch_data()
    proxies = _proxies(data)
    now = utcnow()
    proxy_id = _new_proxy_id(proxies)
    entry = {
        "id": proxy_id,
        "name": body.name,
        "type": body.type,
        "host": body.host,
        "port": body.port,
        "username": body.username,
        "password": body.password,
        "created_at": now,
        "updated_at": now,
    }
    proxies.append(entry)
    save_dispatch_data(data)
    return _proxy_to_config(entry)


def update_yaml_proxy(proxy_id: str, body: ProxyUpdate) -> ProxyConfig:
    data = load_dispatch_data()
    proxies = _proxies(data)
    for item in proxies:
        if item.get("id") != proxy_id:
            continue
        for key, value in body.model_dump(exclude_unset=True).items():
            item[key] = value
        item["updated_at"] = utcnow()
        save_dispatch_data(data)
        return _proxy_to_config(item)
    raise HTTPException(404, f"proxy not found: {proxy_id}")


def delete_yaml_proxy(proxy_id: str) -> None:
    data = load_dispatch_data()
    proxies = _proxies(data)
    for idx, item in enumerate(proxies):
        if item.get("id") == proxy_id:
            proxies.pop(idx)
            save_dispatch_data(data)
            return
    raise HTTPException(404, f"proxy not found: {proxy_id}")


def get_yaml_settings() -> Settings:
    data = load_dispatch_data()
    server_settings = data.get("server_settings") if isinstance(data.get("server_settings"), dict) else {}
    tasks = data.get("tasks") if isinstance(data.get("tasks"), dict) else {}
    return Settings(
        intent_timeout=int(server_settings.get("intent_timeout") or tasks.get("explore", {}).get("conclude_timeout") or 15),
        reason_timeout=int(server_settings.get("reason_timeout") or tasks.get("reason", {}).get("timeout") or 15),
    )


def update_yaml_settings(body: Settings) -> Settings:
    data = load_dispatch_data()
    data["server_settings"] = {
        "intent_timeout": body.intent_timeout,
        "reason_timeout": body.reason_timeout,
    }
    tasks = data.setdefault("tasks", {})
    tasks.setdefault("explore", {})["conclude_timeout"] = body.intent_timeout
    tasks.setdefault("reason", {})["timeout"] = body.reason_timeout
    save_dispatch_data(data)
    return body


def list_yaml_capabilities() -> list[CapabilityCatalogItem]:
    data = load_capabilities_data()
    caps = data.get("capabilities") if isinstance(data.get("capabilities"), dict) else {}
    result: list[CapabilityCatalogItem] = []
    for item in caps.get("mcp_servers") or []:
        payload = dict(item)
        payload["kind"] = "mcp_server"
        payload.setdefault("available", True)
        payload.setdefault("detail", payload.get("transport") or "stdio")
        payload.setdefault("source", "builtin")
        payload.setdefault("args", payload.get("args") or [])
        payload.setdefault("headers", payload.get("headers") or {})
        payload.setdefault("required_skill_ids", payload.get("required_skill_ids") or [])
        payload.setdefault("preferred_mcp_ids", [])
        result.append(CapabilityCatalogItem.model_validate(payload))
    for item in caps.get("skills") or []:
        payload = dict(item)
        payload["kind"] = "skill"
        payload.setdefault("available", True)
        payload.setdefault("detail", "directory")
        payload.setdefault("source", "builtin")
        payload.setdefault("requires_ids", payload.get("requires_ids") or [])
        payload.setdefault("preferred_mcp_ids", payload.get("preferred_mcp_ids") or [])
        result.append(CapabilityCatalogItem.model_validate(payload))
    return result


def upsert_yaml_capability(kind: str, capability_id: str, body: CapabilityAdminRequest) -> CapabilityCatalogItem:
    if kind not in ("mcp_server", "skill"):
        raise HTTPException(400, f"unknown kind: {kind}")
    data = load_capabilities_data()
    caps = data.setdefault("capabilities", {})
    section = "mcp_servers" if kind == "mcp_server" else "skills"
    entries = caps.setdefault(section, [])
    if not isinstance(entries, list):
        raise HTTPException(500, f"dispatch.capabilities.yaml capabilities.{section} must be a list")
    existing_idx = next((idx for idx, item in enumerate(entries) if isinstance(item, dict) and item.get("id") == capability_id), None)
    existing = entries[existing_idx] if existing_idx is not None else {}
    if existing_idx is not None and existing.get("source") not in (None, "user"):
        raise HTTPException(409, f"capability {kind}/{capability_id} is built-in and cannot be modified")
    _validate_capability_links(kind, capability_id, body)
    payload = _capability_body_to_yaml(kind, capability_id, body)
    if existing_idx is None:
        entries.append(payload)
    else:
        entries[existing_idx] = payload
    save_capabilities_data(data)
    return next(item for item in list_yaml_capabilities() if item.kind == kind and item.id == capability_id)


def delete_yaml_capability(kind: str, capability_id: str) -> None:
    if kind not in ("mcp_server", "skill"):
        raise HTTPException(400, f"unknown kind: {kind}")
    data = load_capabilities_data()
    caps = data.setdefault("capabilities", {})
    section = "mcp_servers" if kind == "mcp_server" else "skills"
    entries = caps.setdefault(section, [])
    if not isinstance(entries, list):
        raise HTTPException(500, f"dispatch.capabilities.yaml capabilities.{section} must be a list")
    for idx, item in enumerate(entries):
        if not isinstance(item, dict) or item.get("id") != capability_id:
            continue
        if item.get("source") not in (None, "user"):
            raise HTTPException(409, f"{kind}/{capability_id} is built-in and cannot be deleted")
        entries.pop(idx)
        save_capabilities_data(data)
        return
    raise HTTPException(404, f"{kind} not found: {capability_id}")


def replace_yaml_roles(roles: list[RegisterRoleCatalogItem]) -> list[RoleCatalogItem]:
    data = load_capabilities_data()
    data["roles"] = [
        {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "prompt": item.prompt,
            "default_skill_ids": item.default_skill_ids,
            "task_types": item.task_types or ["bootstrap", "explore", "reason"],
            "detail": item.detail,
            "available": item.available,
        }
        for item in roles
    ]
    save_capabilities_data(data)
    return list_yaml_roles()


def _validate_capability_links(kind: str, capability_id: str, body: CapabilityAdminRequest) -> None:
    catalog = {(item.kind, item.id): item for item in list_yaml_capabilities()}
    if kind == "mcp_server":
        if body.requires_ids:
            raise HTTPException(400, "mcp_server capabilities cannot declare requires_ids")
        if body.preferred_mcp_ids:
            raise HTTPException(400, "mcp_server capabilities cannot declare preferred_mcp_ids")
        for skill_id in body.required_skill_ids:
            if ("skill", skill_id) not in catalog:
                raise HTTPException(400, f"required skill id not in catalog: {skill_id}")
    if kind == "skill":
        if body.required_skill_ids:
            raise HTTPException(400, "skill capabilities cannot declare required_skill_ids")
        if capability_id in body.requires_ids:
            raise HTTPException(400, "a skill cannot require itself")
        for skill_id in body.requires_ids:
            if ("skill", skill_id) not in catalog:
                raise HTTPException(400, f"requires skill id not in catalog: {skill_id}")
        for mcp_id in body.preferred_mcp_ids:
            if ("mcp_server", mcp_id) not in catalog:
                raise HTTPException(400, f"preferred MCP id not in catalog: {mcp_id}")


def _capability_body_to_yaml(kind: str, capability_id: str, body: CapabilityAdminRequest) -> dict[str, Any]:
    common: dict[str, Any] = {
        "id": capability_id,
        "name": body.name,
        "description": body.description,
        "task_types": body.task_types or ["bootstrap", "explore"],
        "use_when": body.use_when,
        "activation_hint": body.activation_hint,
        "detail": body.detail,
        "available": body.available,
        "probe_config": body.probe_config or {},
        "last_probe_status": None,
        "last_probe_at": None,
        "last_probe_message": "",
    }
    if kind == "mcp_server":
        common.update(
            {
                "transport": body.transport or "stdio",
                "source_path": body.source_path,
                "command": body.command,
                "args": body.args,
                "url": body.url,
                "bearer_token_env": body.bearer_token_env,
                "headers": body.headers,
                "required_skill_ids": body.required_skill_ids,
            }
        )
    else:
        common.update(
            {
                "source_path": body.source_path or "",
                "requires_ids": body.requires_ids,
                "preferred_mcp_ids": body.preferred_mcp_ids,
            }
        )
    return _strip_empty_values(common)


def _strip_empty_values(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if item not in (None, "", [], {})
    }


def list_yaml_roles() -> list[RoleCatalogItem]:
    data = load_capabilities_data()
    roles = data.get("roles") if isinstance(data.get("roles"), list) else []
    result: list[RoleCatalogItem] = []
    for item in roles:
        payload = dict(item)
        payload.setdefault("available", True)
        payload.setdefault("detail", "")
        payload.setdefault("prompt_sha256", "")
        result.append(RoleCatalogItem.model_validate(payload))
    return result


def get_yaml_role_snapshot(role_id: str) -> dict[str, Any] | None:
    data = load_capabilities_data()
    roles = data.get("roles") if isinstance(data.get("roles"), list) else []
    for item in roles:
        if not isinstance(item, dict) or item.get("id") != role_id:
            continue
        prompt = str(item.get("prompt") or "")
        if not prompt and item.get("source_path"):
            path = Path(str(item["source_path"]))
            if not path.is_absolute():
                path = capabilities_yaml_path().parent / path
            prompt = path.read_text(encoding="utf-8").strip()
        return {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or item.get("id") or ""),
            "prompt": prompt,
            "prompt_sha256": _text_sha256(prompt),
            "default_skill_ids": list(item.get("default_skill_ids") or []),
        }
    return None


def config_revision() -> dict[str, str]:
    return {
        "dispatch_sha256": _sha256(dispatch_yaml_path()),
        "capabilities_sha256": _sha256(capabilities_yaml_path()),
    }


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise HTTPException(500, f"config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise HTTPException(500, f"config file must contain a mapping: {path}")
    return data


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as tmp:
        tmp.write(text)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    try:
        tmp_path.replace(path)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        if exc.errno != errno.EBUSY:
            raise
        # Docker single-file bind mounts cannot be atomically replaced
        # (os.replace returns EBUSY). Fall back to in-place overwrite so
        # mounted config files remain editable from the server container.
        _overwrite_yaml(path, text)


def _overwrite_yaml(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _validate_dispatch_data(data: dict[str, Any]) -> None:
    validation_data = _dispatch_validation_data(data)
    with NamedTemporaryFile(
        "w",
        suffix=".yaml",
        encoding="utf-8",
        dir=str(dispatch_yaml_path().parent),
        delete=False,
    ) as tmp:
        yaml.safe_dump(validation_data, tmp, sort_keys=False, allow_unicode=True)
        tmp_path = Path(tmp.name)
    try:
        with _validation_env_defaults(validation_data):
            DispatchConfig.load(tmp_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"invalid dispatch config: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)


def _workers(data: dict[str, Any]) -> list[dict[str, Any]]:
    workers = data.setdefault("workers", [])
    if not isinstance(workers, list):
        raise HTTPException(500, "dispatch.yaml workers must be a list")
    return workers


def _proxies(data: dict[str, Any]) -> list[dict[str, Any]]:
    proxies = data.setdefault("proxies", [])
    if not isinstance(proxies, list):
        raise HTTPException(500, "dispatch.yaml proxies must be a list")
    return proxies


def _worker_index(workers: list[dict[str, Any]], profile_id: str) -> int | None:
    for idx, worker in enumerate(workers):
        if _worker_profile_id(worker) == profile_id:
            return idx
    return None


def _worker_profile_id(worker: dict[str, Any]) -> str:
    name = str(worker.get("name") or "").strip()
    if _is_manual_worker(worker):
        return name
    return f"ai_seed_{_slug(name)}"


def _worker_to_profile(worker: dict[str, Any]) -> AiProfile:
    worker_type = str(worker.get("type") or "")
    env = worker.get("env") if isinstance(worker.get("env"), dict) else {}
    model_key = _env_key(worker_type, "MODEL")
    base_url_key = _env_key(worker_type, "BASE_URL")
    auth_key = _auth_key(worker_type)
    model = str(env.get(model_key) or "")
    base_url = str(env.get(base_url_key) or "")
    if base_url == "http://localhost":
        base_url = ""
    sk = str(env.get(auth_key) or "")
    if re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*(?::?-cairn-placeholder)?\}", sk):
        sk = ""
    models = [str(item) for item in worker.get("models") or [] if str(item).strip()]
    if model and model not in models:
        models.append(model)
    now = str(worker.get("updated_at") or worker.get("created_at") or utcnow())
    profile_id = _worker_profile_id(worker)
    seeded_from_worker = None if _is_manual_worker(worker) else str(worker.get("name") or "")
    return AiProfile(
        id=profile_id,
        name=str(worker.get("display_name") or worker.get("name") or profile_id),
        description=str(worker.get("description") or ""),
        worker_type=worker_type,  # type: ignore[arg-type]
        provider=str(env.get(_provider_key(worker_type)) or ""),
        base_url=base_url,
        model=model,
        api_key_env=auth_key,
        available=bool(worker.get("available", True)),
        detail=str(worker.get("detail") or ""),
        healthcheck_timeout=float(worker.get("healthcheck_timeout") or 1.0),
        model_reasoning_effort=worker.get("model_reasoning_effort"),
        warnings=[w for w in [auth_env_warning(worker_type, auth_key)] if w],
        seeded_from_worker=seeded_from_worker,
        last_health_ok=worker.get("last_health_ok"),
        last_health_message=str(worker.get("last_health_message") or ""),
        last_health_at=worker.get("last_health_at"),
        models=models,
        sk=sk,
        created_at=str(worker.get("created_at") or now),
        updated_at=now,
    )


def _profile_body_to_worker(profile_id: str, body: AiProfileCreate) -> dict[str, Any]:
    values = body.model_dump()
    values["sk"] = body.sk
    values["id"] = profile_id
    return _profile_values_to_worker(values)


def _profile_values_to_worker(values: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    worker = deepcopy(existing or {})
    worker_type = values["worker_type"]
    env = dict(worker.get("env") if isinstance(worker.get("env"), dict) else {})
    env[_env_key(worker_type, "MODEL")] = values["model"]
    env[_env_key(worker_type, "BASE_URL")] = values.get("base_url") or "http://localhost"
    auth_key = _auth_key(worker_type)
    env[auth_key] = values.get("sk") or f"${{{auth_key}:-cairn-placeholder}}"
    provider_key = _provider_key(worker_type)
    if values.get("provider"):
        env[provider_key] = values["provider"]
    elif provider_key in env:
        env.pop(provider_key, None)
    now = utcnow()
    worker.clear()
    worker.update(
        {
            "name": values["id"],
            "display_name": values.get("name") or values["id"],
            "description": values.get("description") or "",
            "type": worker_type,
            "task_types": (existing or {}).get("task_types") or ["bootstrap", "reason", "explore"],
            "max_running": int((existing or {}).get("max_running") or 1),
            "priority": int((existing or {}).get("priority") or 0),
            "models": _profile_models_for_yaml(values),
            "env": env,
        }
    )
    if "available" in values:
        worker["available"] = bool(values["available"])
    if values.get("detail"):
        worker["detail"] = values["detail"]
    if values.get("healthcheck_timeout"):
        worker["healthcheck_timeout"] = float(values["healthcheck_timeout"])
    if values.get("model_reasoning_effort"):
        worker["model_reasoning_effort"] = values["model_reasoning_effort"]
    return worker


def _env_key(worker_type: str, suffix: str) -> str:
    for key in WORKER_ENV_KEYS.get(worker_type, ()):  # type: ignore[arg-type]
        if key.endswith(f"_{suffix}"):
            return key
    return f"{worker_type.upper()}_{suffix}"


def _auth_key(worker_type: str) -> str:
    return canonical_auth_env(worker_type) or _env_key(worker_type, "API_KEY")


def _provider_key(worker_type: str) -> str:
    return "CODEX_PROVIDER" if worker_type == "codex" else "ANTHROPIC_PROVIDER"


def _profile_models_for_yaml(values: dict[str, Any]) -> list[str]:
    model = values.get("model")
    models = [item for item in values.get("models") or [] if item != model]
    if model:
        models.append(model)
    return list(dict.fromkeys(models))


def _new_ai_id(name: str, workers: list[dict[str, Any]]) -> str:
    base = f"ai_{_slug(name) or 'profile'}"
    candidate = base
    used = {_worker_profile_id(worker) for worker in workers}
    counter = 2
    while candidate in used:
        candidate = f"{base}_{counter}"
        counter += 1
    return candidate[:64]


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip()).strip("_").lower()


def _is_manual_worker(worker: dict[str, Any]) -> bool:
    return str(worker.get("name") or "").strip().startswith("ai_")


def _sync_worker_to_yaml_worker(item: Any, *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    worker_type = str(item.worker_type)
    auth_key = _auth_key(worker_type)
    model_key = _env_key(worker_type, "MODEL")
    base_url_key = _env_key(worker_type, "BASE_URL")
    provider_key = _provider_key(worker_type)
    models = list(getattr(item, "models", None) or [])
    if item.model and item.model not in models:
        models.insert(0, item.model)
    elif item.model in models:
        models = [item.model] + [model for model in models if model != item.model]
    existing_env = existing.get("env") if isinstance(existing, dict) and isinstance(existing.get("env"), dict) else {}
    existing_secret = existing_env.get(auth_key) if isinstance(existing_env, dict) else None
    env = {
        model_key: item.model,
        base_url_key: item.base_url or "http://localhost",
        auth_key: item.sk if item.sk is not None else (existing_secret or f"${{{auth_key}}}"),
    }
    if item.provider:
        env[provider_key] = item.provider
    worker: dict[str, Any] = {
        "name": item.name,
        "type": worker_type,
        "task_types": ["bootstrap", "reason", "explore"],
        "max_running": 1,
        "priority": 0,
        "models": models,
        "env": env,
        "updated_at": utcnow(),
    }
    if item.model_reasoning_effort:
        worker["model_reasoning_effort"] = item.model_reasoning_effort
    return worker


def _new_proxy_id(proxies: list[dict[str, Any]]) -> str:
    used = {str(item.get("id") or "") for item in proxies}
    index = 1
    while True:
        candidate = f"proxy_{index:03d}"
        if candidate not in used:
            return candidate
        index += 1


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


@contextmanager
def _validation_env_defaults(data: dict[str, Any]) -> Iterator[None]:
    missing = {
        name: "cairn-validation-placeholder"
        for name in _env_placeholder_names(data)
        if os.environ.get(name) is None
    }
    if not missing:
        yield
        return
    old = {name: os.environ.get(name) for name in missing}
    try:
        os.environ.update(missing)
        yield
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _env_placeholder_names(data: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(data, dict):
        for value in data.values():
            names.update(_env_placeholder_names(value))
    elif isinstance(data, list):
        for value in data:
            names.update(_env_placeholder_names(value))
    elif isinstance(data, str):
        names.update(match.group(1) for match in re.finditer(r"\$\{([A-Za-z_][A-Za-z0-9_]*)", data))
    return names


def _proxy_to_config(item: dict[str, Any]) -> ProxyConfig:
    created = str(item.get("created_at") or utcnow())
    updated = str(item.get("updated_at") or created)
    return ProxyConfig(
        id=str(item.get("id") or ""),
        name=str(item.get("name") or ""),
        type=item.get("type") or "socks5",
        host=str(item.get("host") or ""),
        port=int(item.get("port") or 1),
        has_auth=bool(item.get("username") or item.get("password")),
        username=item.get("username"),
        password=item.get("password"),
        created_at=created,
        updated_at=updated,
    )


def _proxy_summary(item: ProxyConfig) -> ProxySummary:
    return ProxySummary(
        id=item.id,
        name=item.name,
        type=item.type,
        host=item.host,
        port=item.port,
        has_auth=item.has_auth,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _sha256(path: Path) -> str:
    import hashlib

    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
