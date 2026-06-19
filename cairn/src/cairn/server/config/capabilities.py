from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from cairn.server.config.files import load_resources_data, save_resources_data, utcnow
from cairn.server.schemas import CapabilityAdminRequest, CapabilityCatalogItem, McpImportResponse
from cairn.shared.task_types import default_capability_task_type_names


def list_yaml_capabilities() -> list[CapabilityCatalogItem]:
    data = load_resources_data()
    caps_raw = data.get("capabilities")
    caps = caps_raw if isinstance(caps_raw, dict) else {}
    result: list[CapabilityCatalogItem] = []
    for item in caps.get("mcp_servers") or []:
        payload = dict(item)
        payload["kind"] = "mcp_server"
        if not payload.get("transport"):
            raise HTTPException(500, f"mcp_server {payload.get('id') or '<unknown>'} is missing required transport")
        payload.setdefault("available", True)
        payload.setdefault("detail", payload["transport"])
        payload.setdefault("source", "builtin")
        payload.setdefault("args", payload.get("args") or [])
        payload.setdefault("env", payload.get("env") or {})
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
    data = load_resources_data()
    caps = data.setdefault("capabilities", {})
    section = "mcp_servers" if kind == "mcp_server" else "skills"
    entries = caps.setdefault(section, [])
    if not isinstance(entries, list):
        raise HTTPException(500, f"config.resources.yaml capabilities.{section} must be a list")
    existing_idx = next((idx for idx, item in enumerate(entries) if isinstance(item, dict) and item.get("id") == capability_id), None)
    existing = entries[existing_idx] if existing_idx is not None else {}
    if existing_idx is not None and existing.get("source") != "user":
        raise HTTPException(409, f"capability {kind}/{capability_id} is built-in and cannot be modified")
    _validate_capability_links(kind, capability_id, body)
    payload = _capability_body_to_yaml(
        kind,
        capability_id,
        body,
        source=str(existing.get("source") or "builtin") if existing_idx is not None else "user",
    )
    for key in ("last_probe_status", "last_probe_at", "last_probe_message"):
        if existing_idx is not None and key in existing:
            payload[key] = existing[key]
    if existing_idx is None:
        entries.append(payload)
    else:
        entries[existing_idx] = payload
    save_resources_data(data)
    return next(item for item in list_yaml_capabilities() if item.kind == kind and item.id == capability_id)


def import_mcp_servers(payload: dict[str, dict]) -> McpImportResponse:
    data = load_resources_data()
    caps = data.setdefault("capabilities", {})
    entries = caps.setdefault("mcp_servers", [])
    if not isinstance(entries, list):
        raise HTTPException(500, "config.resources.yaml capabilities.mcp_servers must be a list")
    created: list[str] = []
    updated: list[str] = []
    conflicts: list[str] = []
    for raw_id, spec in payload.items():
        capability_id = str(raw_id or "").strip()
        if not capability_id:
            continue
        existing_idx = next((idx for idx, item in enumerate(entries) if isinstance(item, dict) and item.get("id") == capability_id), None)
        existing = entries[existing_idx] if existing_idx is not None else {}
        if existing_idx is not None and existing.get("source") != "user":
            conflicts.append(capability_id)
            continue
        body = _mcp_import_spec_to_body(capability_id, spec)
        _validate_capability_links("mcp_server", capability_id, body)
        item = _capability_body_to_yaml("mcp_server", capability_id, body, source="user")
        if existing_idx is None:
            entries.append(item)
            created.append(capability_id)
        else:
            entries[existing_idx] = item
            updated.append(capability_id)
    if created or updated:
        save_resources_data(data)
    return McpImportResponse(created=created, updated=updated, conflicts=conflicts)


def delete_yaml_capability(kind: str, capability_id: str) -> None:
    if kind not in ("mcp_server", "skill"):
        raise HTTPException(400, f"unknown kind: {kind}")
    data = load_resources_data()
    caps = data.setdefault("capabilities", {})
    section = "mcp_servers" if kind == "mcp_server" else "skills"
    entries = caps.setdefault(section, [])
    if not isinstance(entries, list):
        raise HTTPException(500, f"config.resources.yaml capabilities.{section} must be a list")
    for idx, item in enumerate(entries):
        if not isinstance(item, dict) or item.get("id") != capability_id:
            continue
        entries.pop(idx)
        save_resources_data(data)
        return
    raise HTTPException(404, f"{kind} not found: {capability_id}")


def update_yaml_mcp_probe_results(results: list[dict[str, str]]) -> list[CapabilityCatalogItem]:
    if not results:
        return []
    data = load_resources_data()
    caps = data.setdefault("capabilities", {})
    entries = caps.setdefault("mcp_servers", [])
    if not isinstance(entries, list):
        raise HTTPException(500, "config.resources.yaml capabilities.mcp_servers must be a list")
    by_id = {
        str(result.get("capability_id") or "").strip(): result
        for result in results
        if str(result.get("capability_id") or "").strip()
    }
    if not by_id:
        return []
    at = utcnow()
    updated_ids: list[str] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        capability_id = str(item.get("id") or "").strip()
        result = by_id.get(capability_id)
        if result is None:
            continue
        status = str(result.get("status") or "error").strip()
        if status not in ("ok", "warn", "error"):
            status = "error"
        item["last_probe_status"] = status
        item["last_probe_at"] = at
        item["last_probe_message"] = str(result.get("message") or "").strip()
        item["available"] = status == "ok"
        updated_ids.append(capability_id)
    if updated_ids:
        save_resources_data(data, reload_dispatcher=False)
    catalog = {
        item.id: item
        for item in list_yaml_capabilities()
        if item.kind == "mcp_server" and item.id in updated_ids
    }
    return [catalog[item_id] for item_id in updated_ids if item_id in catalog]


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


def _capability_body_to_yaml(
    kind: str,
    capability_id: str,
    body: CapabilityAdminRequest,
    *,
    source: str = "user",
) -> dict[str, Any]:
    _validate_capability_body(kind, capability_id, body)
    common: dict[str, Any] = {
        "id": capability_id,
        "name": body.name,
        "source": source,
        "description": body.description,
        "task_types": body.task_types or list(default_capability_task_type_names()),
        "use_when": body.use_when,
        "activation_hint": body.activation_hint,
        "detail": body.detail,
        "available": body.available,
        "probe_config": body.probe_config or {},
    }
    if kind == "mcp_server":
        if body.transport not in ("stdio", "http"):
            raise HTTPException(400, "mcp_server transport must be 'stdio' or 'http'")
        common.update(
            {
                "transport": body.transport,
                "source_path": body.source_path,
                "command": body.command,
                "args": body.args,
                "env": body.env,
                "url": body.url,
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


def _validate_capability_body(kind: str, capability_id: str, body: CapabilityAdminRequest) -> None:
    if kind == "mcp_server":
        if body.transport not in ("stdio", "http"):
            raise HTTPException(400, "mcp_server transport must be 'stdio' or 'http'")
        if body.transport == "stdio" and not (body.command or "").strip():
            raise HTTPException(400, f"mcp_server {capability_id}: stdio transport requires command")
        if body.transport == "http" and not (body.url or "").strip():
            raise HTTPException(400, f"mcp_server {capability_id}: http transport requires url")
    elif kind == "skill":
        if not (body.source_path or "").strip():
            raise HTTPException(400, f"skill {capability_id}: source_path is required")
    else:
        raise HTTPException(400, f"unknown kind: {kind}")


def _mcp_import_spec_to_body(capability_id: str, spec: dict[str, Any]) -> CapabilityAdminRequest:
    if not isinstance(spec, dict):
        raise HTTPException(400, f"mcp server {capability_id}: spec must be an object")
    source = dict(spec)
    url = source.get("url") or source.get("httpUrl")
    command = source.get("command")
    transport = "http" if url and not command else "stdio"
    raw_args = source.get("args")
    raw_env = source.get("env")
    raw_headers = source.get("headers")
    args = raw_args if isinstance(raw_args, list) else []
    env = raw_env if isinstance(raw_env, dict) else {}
    headers = raw_headers if isinstance(raw_headers, dict) else {}
    return CapabilityAdminRequest(
        id=capability_id,
        name=str(source.get("name") or capability_id),
        description=str(source.get("description") or ""),
        task_types=list(default_capability_task_type_names()),
        transport=transport,
        command=str(command or "") if command else None,
        args=[str(item) for item in args],
        env={str(key): str(value) for key, value in env.items()},
        url=str(url or "") if url else None,
        headers={str(key): str(value) for key, value in headers.items()},
        available=True,
    )


def _strip_empty_values(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if item not in (None, "", [], {})
    }
