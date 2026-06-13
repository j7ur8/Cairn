from __future__ import annotations

from pydantic import BaseModel, Field

from cairn.server.models_pkg.capability_catalog import CapabilityCatalogItem, CapabilityHealthEntry


class CapabilityAdminRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    task_types: list[str] = Field(default_factory=list)
    requires_ids: list[str] = Field(default_factory=list)
    required_skill_ids: list[str] = Field(default_factory=list)
    use_when: list[str] = Field(default_factory=list)
    activation_hint: str = ""
    preferred_mcp_ids: list[str] = Field(default_factory=list)
    probe_config: dict = Field(default_factory=dict)
    detail: str = ""
    available: bool = True
    source_path: str | None = None
    transport: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)


class CapabilityAdminResponse(BaseModel):
    catalog: list[CapabilityCatalogItem]
    health: dict[str, list[CapabilityHealthEntry]] = Field(default_factory=dict)
