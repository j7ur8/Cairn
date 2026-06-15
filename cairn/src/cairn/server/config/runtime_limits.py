from __future__ import annotations

from fastapi import HTTPException

from cairn.server.config.files import load_dispatch_data, save_dispatch_data
from cairn.shared.contracts import ContainerLimits, RuntimeLimits


def get_runtime_limits() -> RuntimeLimits:
    data = load_dispatch_data()
    dispatcher = data.get("dispatcher")
    if not isinstance(dispatcher, dict):
        raise HTTPException(500, "dispatch.yaml dispatcher section missing")
    runtime = dispatcher.get("runtime")
    if not isinstance(runtime, dict):
        raise HTTPException(500, "dispatch.yaml dispatcher.runtime section missing")
    missing = [k for k in (
        "max_workers", "max_running_projects", "max_project_workers",
        "interval", "healthcheck_timeout", "prompt_group",
    ) if k not in runtime]
    if missing:
        raise HTTPException(500, f"dispatch.yaml dispatcher.runtime missing: {', '.join(missing)}")
    return RuntimeLimits(
        max_workers=int(runtime["max_workers"]),
        max_running_projects=int(runtime["max_running_projects"]),
        max_project_workers=int(runtime["max_project_workers"]),
        interval=int(runtime["interval"]),
        healthcheck_timeout=int(runtime["healthcheck_timeout"]),
        prompt_group=str(runtime["prompt_group"]),
    )


def update_runtime_limits(body: RuntimeLimits) -> RuntimeLimits:
    if body.max_project_workers > body.max_workers:
        raise HTTPException(400, "max_project_workers cannot exceed max_workers")
    data = load_dispatch_data()
    dispatcher = data.setdefault("dispatcher", {})
    if not isinstance(dispatcher, dict):
        raise HTTPException(500, "dispatch.yaml dispatcher must be a mapping")
    dispatcher["runtime"] = body.model_dump()
    save_dispatch_data(data)
    return body


def get_container_limits() -> ContainerLimits:
    data = load_dispatch_data()
    worker_runtime = data.get("worker_runtime")
    if not isinstance(worker_runtime, dict):
        raise HTTPException(500, "dispatch.yaml worker_runtime section missing")
    container = worker_runtime.get("container")
    if not isinstance(container, dict):
        raise HTTPException(500, "dispatch.yaml worker_runtime.container section missing")
    return ContainerLimits(
        mem_limit=container.get("mem_limit"),
        pids_limit=container.get("pids_limit"),
        nano_cpus=container.get("nano_cpus"),
    )


def update_container_limits(body: ContainerLimits) -> ContainerLimits:
    data = load_dispatch_data()
    worker_runtime = data.setdefault("worker_runtime", {})
    if not isinstance(worker_runtime, dict):
        raise HTTPException(500, "dispatch.yaml worker_runtime must be a mapping")
    container = worker_runtime.setdefault("container", {})
    if not isinstance(container, dict):
        raise HTTPException(500, "dispatch.yaml worker_runtime.container must be a mapping")
    if body.mem_limit is not None:
        container["mem_limit"] = body.mem_limit
    else:
        container.pop("mem_limit", None)
    if body.pids_limit is not None:
        container["pids_limit"] = body.pids_limit
    else:
        container.pop("pids_limit", None)
    if body.nano_cpus is not None:
        container["nano_cpus"] = body.nano_cpus
    else:
        container.pop("nano_cpus", None)
    save_dispatch_data(data)
    return body
