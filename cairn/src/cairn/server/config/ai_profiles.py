from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from fastapi import HTTPException

from cairn.server.config.files import load_dispatch_data, save_dispatch_data, utcnow
from cairn.server.models_pkg.ai_profiles import (
    AiProfile,
    AiProfileCreate,
    AiProfileUpdate,
    auth_env_warning,
    canonical_auth_env,
)
from cairn.shared.config import WORKER_ENV_KEYS
from cairn.shared.task_types import default_worker_task_type_names


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
    cleaned = [item.strip() for item in models if item and item.strip()]
    workers[idx]["models"] = list(dict.fromkeys(cleaned))
    workers[idx]["updated_at"] = utcnow()
    save_dispatch_data(data, reload_dispatcher=False)


def _workers(data: dict[str, Any]) -> list[dict[str, Any]]:
    worker_pool = data.setdefault("worker_pool", {})
    if not isinstance(worker_pool, dict):
        raise HTTPException(500, "dispatch.yaml worker_pool must be a mapping")
    workers = worker_pool.setdefault("workers", [])
    if not isinstance(workers, list):
        raise HTTPException(500, "dispatch.yaml worker_pool.workers must be a list")
    return workers


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
    env_raw = worker.get("env")
    env = env_raw if isinstance(env_raw, dict) else {}
    model_key = _env_key(worker_type, "MODEL")
    base_url_key = _env_key(worker_type, "BASE_URL")
    auth_key = _auth_key(worker_type)
    model = str(env.get(model_key) or "")
    base_url = str(env.get(base_url_key) or "")
    if base_url == "http://localhost":
        base_url = ""
    sk = str(env.get(auth_key) or "")
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
    env_raw = worker.get("env")
    env = dict(env_raw if isinstance(env_raw, dict) else {})
    env[_env_key(worker_type, "MODEL")] = values["model"]
    env[_env_key(worker_type, "BASE_URL")] = values.get("base_url") or "http://localhost"
    auth_key = _auth_key(worker_type)
    env[auth_key] = values.get("sk") or ""
    provider_key = _provider_key(worker_type)
    if values.get("provider"):
        env[provider_key] = values["provider"]
    elif provider_key in env:
        env.pop(provider_key, None)
    worker.clear()
    worker.update(
        {
            "name": values["id"],
            "display_name": values.get("name") or values["id"],
            "description": values.get("description") or "",
            "type": worker_type,
            "task_types": (existing or {}).get("task_types") or list(default_worker_task_type_names()),
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
    for key in WORKER_ENV_KEYS.get(worker_type, ()):  # type: ignore[call-overload]
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
