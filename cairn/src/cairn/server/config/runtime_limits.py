from __future__ import annotations

from fastapi import HTTPException

from cairn.server.config.files import load_dispatch_data, load_server_config_data, save_dispatch_data
from cairn.shared.contracts import ContainerLimits, RuntimeLimits


def get_runtime_limits() -> RuntimeLimits:
    data = load_dispatch_data()
    dispatcher = data.get("dispatcher")
    if not isinstance(dispatcher, dict):
        raise HTTPException(500, "config.yaml dispatcher section missing")
    runtime = dispatcher.get("runtime")
    if not isinstance(runtime, dict):
        raise HTTPException(500, "config.yaml dispatcher.runtime section missing")
    missing = [k for k in (
        "max_workers", "max_running_projects", "max_project_workers",
        "interval", "healthcheck_timeout",
    ) if k not in runtime]
    if missing:
        raise HTTPException(500, f"config.yaml dispatcher.runtime missing: {', '.join(missing)}")
    return RuntimeLimits(
        max_workers=int(runtime["max_workers"]),
        max_running_projects=int(runtime["max_running_projects"]),
        max_project_workers=int(runtime["max_project_workers"]),
        interval=int(runtime["interval"]),
        healthcheck_timeout=int(runtime["healthcheck_timeout"]),
    )


def update_runtime_limits(body: RuntimeLimits) -> RuntimeLimits:
    if body.max_project_workers > body.max_workers:
        raise HTTPException(400, "max_project_workers cannot exceed max_workers")
    data = load_dispatch_data()
    dispatcher = data.setdefault("dispatcher", {})
    if not isinstance(dispatcher, dict):
        raise HTTPException(500, "config.yaml dispatcher must be a mapping")
    dispatcher["runtime"] = body.model_dump()
    save_dispatch_data(data)
    return body


def get_container_limits() -> ContainerLimits:
    data = load_server_config_data()
    runner = data.get("runner")
    if not isinstance(runner, dict):
        raise HTTPException(500, "server.yaml runner section missing")
    resources = runner.get("resources")
    if not isinstance(resources, dict):
        raise HTTPException(500, "server.yaml runner.resources section missing")
    return ContainerLimits(
        mem_limit=resources.get("mem_limit"),
        pids_limit=resources.get("pids_limit"),
        nano_cpus=resources.get("nano_cpus"),
    )


def update_container_limits(body: ContainerLimits) -> ContainerLimits:
    raise HTTPException(405, "container limits are fixed in server.yaml and are not editable through the API")
