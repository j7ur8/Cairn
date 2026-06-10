from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from cairn.shared.task_types import default_capability_task_type_names
from cairn.server.config.files import load_capabilities_data, save_capabilities_data
from cairn.server.models_pkg.capabilities import CapabilityAdminRequest, CapabilityCatalogItem


def list_yaml_capabilities() -> list[CapabilityCatalogItem]:
    data = load_capabilities_data()
    caps = data.get("capabilities") if isinstance(data.get("capabilities"), dict) else {}
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
        "task_types": body.task_types or list(default_capability_task_type_names()),
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
        if body.transport not in ("stdio", "http"):
            raise HTTPException(400, "mcp_server transport must be 'stdio' or 'http'")
        common.update(
            {
                "transport": body.transport,
                "source_path": body.source_path,
                "command": body.command,
                "args": body.args,
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


def _strip_empty_values(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if item not in (None, "", [], {})
    }

