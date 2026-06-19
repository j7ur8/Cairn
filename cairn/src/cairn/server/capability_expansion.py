"""Capability selection expansion and project capability views."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cairn.server.schemas import (
    CapabilityCatalogItem,
    CapabilitySelection,
    TaskCapabilities,
    TaskCapabilitiesMap,
    TaskCapabilitySelectionMap,
    task_capabilities_map,
)
from cairn.shared.capability_projection import project_capability_tasks_payload
from cairn.shared.task_types import builtin_task_type_names

TASK_TYPES: tuple[str, ...] = builtin_task_type_names()


@dataclass
class CatalogEntry:
    item: CapabilityCatalogItem
    source_path: str | None
    transport: str | None
    command: str | None
    args: list[str]
    url: str | None
    headers: dict[str, str]


def selected_capabilities_to_internal(
    selections: TaskCapabilitySelectionMap | None,
) -> TaskCapabilitiesMap:
    """Convert public explicit selections into the internal expansion shape."""
    out = task_capabilities_map(None)
    if not isinstance(selections, dict):
        return out
    for task in TASK_TYPES:
        selection = selections.get(task) or CapabilitySelection()
        out[task] = TaskCapabilities.model_construct(
            mcp_server_ids=list(selection.mcp_server_ids),
            skill_ids=list(selection.skill_ids),
            user_mcp_server_ids=list(selection.mcp_server_ids),
            user_skill_ids=list(selection.skill_ids),
            role_default_skill_ids=[],
        )
    return out


def catalog_map_from_items(items: list[CapabilityCatalogItem]) -> dict[tuple[str, str], CatalogEntry]:
    return {
        (item.kind, item.id): CatalogEntry(
            item=item,
            source_path=item.source_path,
            transport=item.transport,
            command=item.command,
            args=item.args,
            url=item.url,
            headers=item.headers,
        )
        for item in items
    }


def expand_task_capabilities(
    per_task: TaskCapabilitiesMap,
    catalog: dict[tuple[str, str], CatalogEntry],
    role_default_skill_ids: list[str] | None = None,
) -> tuple[TaskCapabilitiesMap, list[str]]:
    """Validate ids and expand requires in-place."""
    errors: list[str] = []
    expanded: TaskCapabilitiesMap = {}
    for task in TASK_TYPES:
        selection = per_task.get(task) or TaskCapabilities()
        mcp_ids = list(selection.user_mcp_server_ids or selection.mcp_server_ids)
        if selection.user_skill_ids:
            skill_ids = list(selection.user_skill_ids)
        elif selection.role_default_skill_ids:
            skill_ids = [
                sid for sid in selection.skill_ids
                if sid not in selection.role_default_skill_ids
            ]
        else:
            skill_ids = list(selection.skill_ids)
        user_mcp = list(mcp_ids)
        user_skill = list(skill_ids)
        role_default_skills = _role_default_skills_for_task(role_default_skill_ids or [], task, catalog)
        role_default_skills.extend(
            sid for sid in selection.role_default_skill_ids if sid not in role_default_skills
        )

        keep_mcp: list[str] = []
        for cid in mcp_ids:
            entry = catalog.get(("mcp_server", cid))
            if entry is None:
                errors.append(f"{task}: mcp_server {cid} not in catalog")
                continue
            if not entry.item.available:
                errors.append(f"{task}: mcp_server {cid} is unavailable")
                continue
            if task not in entry.item.task_types:
                errors.append(
                    f"{task}: mcp_server {cid} does not enable task_type={task}"
                )
                continue
            keep_mcp.append(cid)
        keep_skill: list[str] = []
        for cid in list(dict.fromkeys(skill_ids + role_default_skills)):
            entry = catalog.get(("skill", cid))
            if entry is None:
                errors.append(f"{task}: skill {cid} not in catalog")
                continue
            if not entry.item.available:
                errors.append(f"{task}: skill {cid} is unavailable")
                continue
            if task not in entry.item.task_types:
                errors.append(
                    f"{task}: skill {cid} does not enable task_type={task}"
                )
                continue
            keep_skill.append(cid)

        mcp_required_auto: list[str] = []
        mcp_required_seen: set[str] = set()
        for mid in keep_mcp:
            entry = catalog.get(("mcp_server", mid))
            if entry is None:
                continue
            for sid in entry.item.required_skill_ids:
                if sid in keep_skill or sid in mcp_required_auto or sid in mcp_required_seen:
                    continue
                if sid in keep_skill:
                    mcp_required_seen.add(sid)
                    continue
                skill_entry = catalog.get(("skill", sid))
                if skill_entry is None or not skill_entry.item.available:
                    continue
                if task not in skill_entry.item.task_types:
                    continue
                mcp_required_auto.append(sid)
                mcp_required_seen.add(sid)

        auto_added: list[str] = list(mcp_required_auto)
        visited: set[str] = set(mcp_required_seen)
        queue: list[str] = list(keep_skill) + list(mcp_required_auto)
        while queue:
            sid = queue.pop()
            if sid in visited:
                continue
            visited.add(sid)
            entry = catalog.get(("skill", sid))
            if entry is None:
                continue
            for child in entry.item.requires_ids:
                if child in keep_skill or child in auto_added:
                    continue
                child_entry = catalog.get(("skill", child))
                if child_entry is None or not child_entry.item.available:
                    continue
                if task not in child_entry.item.task_types:
                    continue
                auto_added.append(child)
                queue.append(child)

        expanded[task] = TaskCapabilities.model_construct(
            mcp_server_ids=list(dict.fromkeys(keep_mcp)),
            skill_ids=list(dict.fromkeys(keep_skill + auto_added)),
            user_mcp_server_ids=user_mcp,
            user_skill_ids=user_skill,
            role_default_skill_ids=[
                sid for sid in role_default_skills
                if sid in keep_skill or sid in auto_added
            ],
        )
    return expanded, errors


def _role_default_skills_for_task(
    skill_ids: list[str],
    task: str,
    catalog: dict[tuple[str, str], CatalogEntry],
) -> list[str]:
    out: list[str] = []
    for sid in skill_ids:
        if sid in out:
            continue
        entry = catalog.get(("skill", sid))
        if entry is None or not entry.item.available:
            continue
        if task not in entry.item.task_types:
            continue
        out.append(sid)
    return out


def project_capability_tasks(per_task: TaskCapabilitiesMap) -> dict[str, Any]:
    from cairn.server.schemas import ProjectCapabilityTaskState

    return {
        task: ProjectCapabilityTaskState.model_validate(payload)
        for task, payload in project_capability_tasks_payload(per_task).items()
    }


def unavailable_capabilities(
    catalog: list[CapabilityCatalogItem],
    per_task: TaskCapabilitiesMap,
) -> dict[str, list[str]]:
    available_ids = {(item.kind, item.id) for item in catalog if item.available}
    unavailable_mcp: list[str] = []
    unavailable_skill: list[str] = []
    for selection in per_task.values():
        for cid in selection.mcp_server_ids:
            if ("mcp_server", cid) not in available_ids:
                unavailable_mcp.append(cid)
        for cid in selection.skill_ids:
            if ("skill", cid) not in available_ids:
                unavailable_skill.append(cid)
    return {
        "mcp_server_ids": sorted(set(unavailable_mcp)),
        "skill_ids": sorted(set(unavailable_skill)),
    }
