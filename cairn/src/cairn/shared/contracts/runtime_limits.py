from __future__ import annotations

from pydantic import BaseModel, Field


class RuntimeLimits(BaseModel):
    """dispatcher.runtime section — exposed via GET/PUT /runtime-limits."""

    model_config = {"extra": "forbid"}

    max_workers: int = Field(gt=0)
    max_running_projects: int = Field(gt=0)
    max_project_workers: int = Field(gt=0)
    interval: int = Field(gt=0)
    healthcheck_timeout: int = Field(gt=0)


class ContainerLimits(BaseModel):
    """worker.resources limit-only subset - GET/PUT /container-limits.

    ``nano_cpus`` is Docker's native unit (1 CPU = 1e9). The UI exposes
    ``cpus`` as a float; the service layer converts.
    """

    model_config = {"extra": "forbid"}

    mem_limit: str | None = None
    pids_limit: int | None = None
    nano_cpus: int | None = None
    """CPU quota in units of 1e-9 CPUs.  e.g. 1_500_000_000 = 1.5 CPU."""
