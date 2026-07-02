from __future__ import annotations

import json
from typing import Any

from cairn.server.config.capabilities import list_yaml_capabilities
from cairn.server.config.proxies import get_yaml_proxy
from cairn.server.config.settings import get_yaml_settings
from cairn.server.domain.errors import DomainError, NotFoundError
from cairn.server.execution_config import repository
from cairn.server.execution_config.models import TASK_TYPES
from cairn.server.schemas import TaskCapabilities
from cairn.shared.contracts import TaskTimeouts


def load_project_execution_config(conn: Any, project_id: str, task_type: str) -> dict[str, Any]:
    if task_type not in TASK_TYPES:
        raise NotFoundError(f"execution config not found for {project_id}/{task_type}")
    header = repository.get_header(conn, project_id)
    if header is None:
        raise NotFoundError(f"execution config not found for {project_id}/{task_type}")
    timeout_rows = repository.get_timeout_rows(conn, project_id)
    timeout_by_task = {row["task_type"]: row for row in timeout_rows}
    if task_type not in timeout_by_task:
        raise NotFoundError(f"execution config not found for {project_id}/{task_type}")
    ai_by_task = _ai_by_task(repository.get_ai_rows(conn, project_id, task_type))
    caps_by_task = _caps_by_task(repository.get_capability_rows(conn, project_id, task_type))
    return _assemble_task_payload(
        header,
        task_type,
        timeout_by_task,
        ai_by_task,
        caps_by_task,
    )


def load_project_execution_configs(conn: Any, project_id: str) -> dict[str, dict[str, Any]]:
    header = repository.get_header(conn, project_id)
    if header is None:
        return {}
    timeout_rows = repository.get_timeout_rows(conn, project_id)
    timeout_by_task = {row["task_type"]: row for row in timeout_rows}
    ai_by_task = _ai_by_task(repository.get_ai_rows(conn, project_id))
    caps_by_task = _caps_by_task(repository.get_capability_rows(conn, project_id))
    payloads: dict[str, dict[str, Any]] = {}
    for task in TASK_TYPES:
        if task not in timeout_by_task:
            continue
        payloads[task] = _assemble_task_payload(
            header,
            task,
            timeout_by_task,
            ai_by_task,
            caps_by_task,
        )
    return payloads


def _assemble_task_payload(
    header: Any,
    task: str,
    timeout_by_task: dict[str, Any],
    ai_by_task: dict[str, list[dict[str, Any]]],
    caps_by_task: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    settings = _json_or_fallback(header, "settings_json", lambda: get_yaml_settings().model_dump())
    catalog = _json_or_fallback(header, "catalog_json", lambda: [item.model_dump() for item in list_yaml_capabilities()])
    role = json.loads(header["role_json"]) if header["role_json"] else None
    proxy = _proxy_from_header(header)
    revision = {
        "dispatch_sha256": header["dispatch_sha256"],
        "resources_sha256": header["resources_sha256"],
        "prompts_sha256": header["prompts_sha256"],
    }
    prompt_snapshot = json.loads(header["prompts_json"]) if header["prompts_json"] else None
    task_timeouts = _task_timeouts_from_rows(timeout_by_task)
    timeout = timeout_by_task[task]
    task_timeout: dict[str, Any] = {"timeout": timeout["timeout"]}
    if timeout["conclude_timeout"] is not None:
        task_timeout["conclude_timeout"] = timeout["conclude_timeout"]
    return {
        "task_type": task,
        "ai_profiles": ai_by_task.get(task) or [],
        "capabilities": caps_by_task.get(task) or TaskCapabilities().model_dump(),
        "role": role,
        "proxy": proxy,
        "container": _json_or_fallback(header, "container_json", lambda: None),
        "workers": _json_or_fallback(header, "workers_json", lambda: []),
        "proxies": _json_or_fallback(header, "proxies_json", lambda: []),
        "settings": settings,
        "task_timeouts": task_timeouts.model_dump(),
        "task_timeout": task_timeout,
        "catalog": catalog,
        "health": {},
        "config_revision": revision,
        "config_version": int(header["version"]),
        "prompt_snapshot": prompt_snapshot,
    }


def _json_or_fallback(header: Any, key: str, fallback) -> Any:
    try:
        value = header[key]
    except Exception:  # noqa: BLE001 - sqlite Row/SQLAlchemy Row differ on missing keys
        value = None
    if value:
        return json.loads(value)
    return fallback()


def _proxy_from_header(header: Any) -> dict[str, Any] | None:
    proxies = _json_or_fallback(header, "proxies_json", lambda: None)
    proxy_id = header["proxy_id"]
    if isinstance(proxies, list) and proxy_id:
        for proxy in proxies:
            if isinstance(proxy, dict) and proxy.get("id") == proxy_id:
                return proxy
        return None
    if proxy_id:
        try:
            return get_yaml_proxy(proxy_id).model_dump()
        except DomainError as exc:
            if exc.status_code != 404:
                raise
    return None


def _task_timeouts_from_rows(rows_by_task: dict[str, Any]) -> TaskTimeouts:
    raw: dict[str, dict[str, Any]] = {}
    for task in TASK_TYPES:
        row = rows_by_task.get(task)
        if row is None:
            continue
        item: dict[str, Any] = {"timeout": row["timeout"]}
        if row["conclude_timeout"] is not None:
            item["conclude_timeout"] = row["conclude_timeout"]
        raw[task] = item
    return TaskTimeouts.model_validate(raw)


def _ai_by_task(rows: list[Any]) -> dict[str, list[dict[str, Any]]]:
    ai_by_task: dict[str, list[dict[str, Any]]] = {task: [] for task in TASK_TYPES}
    for row in rows:
        ai_by_task.setdefault(row["task_type"], []).append(
            {
                "profile_id": row["profile_id"],
                "task_type": row["task_type"],
                "role": row["role"],
                "position": row["position"],
                "snapshot_name": row["snapshot_name"],
                "snapshot_worker_type": row["snapshot_worker_type"],
                "snapshot_provider": row["snapshot_provider"],
                "snapshot_base_url": row["snapshot_base_url"],
                "snapshot_model": row["snapshot_model"],
                "snapshot_reasoning_type": row["snapshot_reasoning_type"],
                "snapshot_api_key_env": row["snapshot_api_key_env"],
                "snapshot_api_key_value": _row_value(row, "snapshot_api_key_value") or "",
            }
        )
    return ai_by_task


def _row_value(row: Any, key: str) -> Any:
    try:
        return row[key]
    except Exception:  # noqa: BLE001 - missing column on legacy query rows
        return None


def _caps_by_task(rows: list[Any]) -> dict[str, dict[str, Any]]:
    return {
        row["task_type"]: json.loads(row["capabilities_json"])
        for row in rows
    }
