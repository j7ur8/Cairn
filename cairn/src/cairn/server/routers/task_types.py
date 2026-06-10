from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from cairn.shared.task_types import TASK_TYPE_REGISTRY

router = APIRouter(tags=["task-types"])


@router.get("/task-types")
def list_task_types() -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "json_schema": spec.json_schema,
        }
        for spec in TASK_TYPE_REGISTRY.specs()
    ]

