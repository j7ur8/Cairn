from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from cairn.server.models_pkg.capability_catalog import CapabilityCatalogItem, CapabilityHealthEntry
from cairn.shared.task_types import builtin_task_type_names


class CapabilitySelection(BaseModel):
    mcp_server_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)

    @field_validator("mcp_server_ids", "skill_ids")
    @classmethod
    def validate_ids(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = (item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned


TaskCapabilitySelectionMap = dict[str, CapabilitySelection]


def task_capability_selection_map(
    values: dict[str, dict[str, list[str]]] | dict[str, CapabilitySelection] | None,
) -> TaskCapabilitySelectionMap:
    out: TaskCapabilitySelectionMap = {}
    for task in builtin_task_type_names():
        payload = values.get(task) if isinstance(values, dict) else None
        if isinstance(payload, CapabilitySelection):
            out[task] = payload
        elif isinstance(payload, dict):
            out[task] = CapabilitySelection(
                mcp_server_ids=list(payload.get("mcp_server_ids") or []),
                skill_ids=list(payload.get("skill_ids") or []),
            )
        else:
            out[task] = CapabilitySelection()
    return out


class ProjectCapabilitySnapshotItem(BaseModel):
    kind: Literal["mcp_server", "skill"]
    capability_id: str
    source: Literal["selected", "required", "role_default"]


class ProjectCapabilityTaskState(BaseModel):
    selected: CapabilitySelection = Field(default_factory=CapabilitySelection)
    snapshots: list[ProjectCapabilitySnapshotItem] = Field(default_factory=list)


class ProjectCapabilitiesResponse(BaseModel):
    catalog: list[CapabilityCatalogItem]
    tasks: dict[str, ProjectCapabilityTaskState] = Field(default_factory=dict)
    health: dict[str, list[CapabilityHealthEntry]] = Field(default_factory=dict)
    unavailable: dict[str, list[str]] = Field(default_factory=dict)


class ProjectCapabilitiesUpdateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    capabilities: TaskCapabilitySelectionMap
