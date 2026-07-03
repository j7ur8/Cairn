from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ProxyProtocol = Literal["socks5", "socks5h", "http", "https"]
ProxyAuthType = Literal["none", "password"]
ProxyLifecycle = Literal["persistent", "run", "task"]


class ProjectProxyEndpointBase(BaseModel):
    name: str
    protocol: ProxyProtocol = "socks5h"
    host: str
    port: int = Field(gt=0, le=65535)
    auth_type: ProxyAuthType = "none"
    username: str | None = None
    password: str | None = None
    source: str = ""
    lifecycle: ProxyLifecycle = "persistent"
    description: str = ""
    scope: str = ""
    prerequisite_proxy_id: str | None = None
    reachable_from: str = "worker"
    usage_mode: str = "tool_native_proxy"
    run_id: str | None = None
    task_id: str | None = None

    @field_validator("name", "host")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator(
        "username",
        "password",
        "source",
        "description",
        "scope",
        "prerequisite_proxy_id",
        "reachable_from",
        "usage_mode",
        "run_id",
        "task_id",
    )
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class ProjectProxyEndpointCreate(ProjectProxyEndpointBase):
    id: str | None = None


class ProjectProxyEndpointUpdate(BaseModel):
    name: str | None = None
    protocol: ProxyProtocol | None = None
    host: str | None = None
    port: int | None = Field(default=None, gt=0, le=65535)
    auth_type: ProxyAuthType | None = None
    username: str | None = None
    password: str | None = None
    source: str | None = None
    lifecycle: ProxyLifecycle | None = None
    description: str | None = None
    scope: str | None = None
    prerequisite_proxy_id: str | None = None
    reachable_from: str | None = None
    usage_mode: str | None = None
    run_id: str | None = None
    task_id: str | None = None

    @field_validator(
        "name",
        "host",
        "username",
        "password",
        "source",
        "description",
        "scope",
        "prerequisite_proxy_id",
        "reachable_from",
        "usage_mode",
        "run_id",
        "task_id",
    )
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class ProjectProxyEndpoint(ProjectProxyEndpointBase):
    id: str
    project_id: str
    has_auth: bool = False
    health_status: str = "unknown"
    last_test_ok: bool | None = None
    last_test_at: str | None = None
    last_test_message: str = ""
    last_used_at: str | None = None
    last_usage_ok: bool | None = None
    last_usage_message: str = ""
    created_at: str
    updated_at: str


class ProjectProxyChainResult(BaseModel):
    ok: bool
    proxy_id: str
    chain: list[ProjectProxyEndpoint] = Field(default_factory=list)
    reason: str = ""


class ProjectProxyUsageResult(BaseModel):
    ok: bool
    message: str = ""


class ProjectProxyTestRequest(BaseModel):
    target_url: str | None = None
    timeout_seconds: int = Field(default=10, gt=0, le=60)
