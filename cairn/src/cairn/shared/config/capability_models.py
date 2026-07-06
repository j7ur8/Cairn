from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cairn.shared.config.constants import TaskType, _check_known_task_types
from cairn.shared.task_types import builtin_task_type_names


class RuntimeProviderConfig(BaseModel):
    """Dynamic runtime resource provider for a capability."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["cloak_sidecar"]
    resource: Literal["browser_url"]


class McpServerCapabilityConfig(BaseModel):
    """Capability config for one MCP server."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    transport: Literal["stdio", "http"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    healthcheck_timeout: float = Field(default=1.0, gt=0, le=30)
    source_path: str | None = None
    probe_config: dict[str, Any] = Field(default_factory=dict)
    runtime_provider: RuntimeProviderConfig | None = None
    task_types: list[TaskType] = Field(default_factory=lambda: ["bootstrap", "explore"])
    description: str = ""
    detail: str = ""
    available: bool = True
    last_probe_status: str | None = None
    last_probe_at: str | None = None
    last_probe_message: str = ""
    required_skill_ids: list[str] = Field(default_factory=list)
    use_when: list[str] = Field(default_factory=list)
    activation_hint: str = ""

    @field_validator("id", "name", "command", "source_path", "url")
    @classmethod
    def validate_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return value

    @model_validator(mode="after")
    def validate_transport(self) -> McpServerCapabilityConfig:
        if self.transport == "stdio":
            if not self.command:
                raise ValueError(f"mcp_server {self.id}: stdio transport requires 'command'")
        elif self.transport == "http":
            if not self.url:
                raise ValueError(f"mcp_server {self.id}: http transport requires 'url'")
        else:
            raise ValueError(f"mcp_server {self.id}: transport must be 'stdio' or 'http', got {self.transport!r}")
        return self

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("id must not be empty")
        if any(ch.isspace() for ch in text) or "/" in text or "\\" in text:
            raise ValueError("id must not contain whitespace, '/', or '\\'")
        return text

    @field_validator("task_types")
    @classmethod
    def validate_task_types(cls, value: list[TaskType]) -> list[TaskType]:
        if not value:
            raise ValueError("task_types must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("task_types must be unique")
        _check_known_task_types(value)
        return value

    @field_validator("required_skill_ids", "use_when")
    @classmethod
    def validate_string_list(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in value or []:
            key = (item or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped

    @field_validator("activation_hint")
    @classmethod
    def validate_activation_hint(cls, value: str) -> str:
        return value.strip()


class SkillCapabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    source_path: str
    task_types: list[TaskType] = Field(default_factory=lambda: list(builtin_task_type_names()))
    description: str = ""
    use_when: list[str] = Field(default_factory=list)
    preferred_mcp_ids: list[str] = Field(default_factory=list)
    activation_hint: str = ""
    detail: str = ""
    available: bool = True
    requires_ids: list[str] = Field(default_factory=list)
    probe_config: dict[str, Any] = Field(default_factory=dict)
    last_probe_status: str | None = None
    last_probe_at: str | None = None
    last_probe_message: str = ""

    @field_validator("id", "name", "source_path")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("id must not be empty")
        if any(ch.isspace() for ch in text) or "/" in text or "\\" in text:
            raise ValueError("id must not contain whitespace, '/', or '\\'")
        return text

    @field_validator("task_types")
    @classmethod
    def validate_task_types(cls, value: list[TaskType]) -> list[TaskType]:
        if not value:
            raise ValueError("task_types must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("task_types must be unique")
        _check_known_task_types(value)
        return value

    @field_validator("use_when", "preferred_mcp_ids", "requires_ids")
    @classmethod
    def validate_string_list(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in value or []:
            key = (item or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped

    @field_validator("activation_hint")
    @classmethod
    def validate_activation_hint(cls, value: str) -> str:
        return value.strip()


class CapabilitiesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mcp_servers: list[McpServerCapabilityConfig] = Field(default_factory=list)
    skills: list[SkillCapabilityConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> CapabilitiesConfig:
        mcp_ids = [item.id for item in self.mcp_servers]
        skill_ids = [item.id for item in self.skills]
        if len(mcp_ids) != len(set(mcp_ids)):
            raise ValueError("capabilities.mcp_servers ids must be unique")
        if len(skill_ids) != len(set(skill_ids)):
            raise ValueError("capabilities.skills ids must be unique")
        declared_skill_ids = set(skill_ids)
        for mcp in self.mcp_servers:
            for required_skill_id in mcp.required_skill_ids:
                if required_skill_id not in declared_skill_ids:
                    raise ValueError(
                        f"mcp_server {mcp.id} requires skill {required_skill_id!r} "
                        f"but that id is not declared in capabilities.skills"
                    )
        for skill in self.skills:
            for required_skill_id in skill.requires_ids:
                if required_skill_id not in declared_skill_ids:
                    raise ValueError(
                        f"skill {skill.id} requires skill {required_skill_id!r} "
                        f"but that id is not declared in capabilities.skills"
                    )
        declared_mcp_ids = set(mcp_ids)
        for skill in self.skills:
            for preferred_mcp_id in skill.preferred_mcp_ids:
                if preferred_mcp_id not in declared_mcp_ids:
                    raise ValueError(
                        f"skill {skill.id} prefers mcp_server {preferred_mcp_id!r} "
                        f"but that id is not declared in capabilities.mcp_servers"
                    )
        return self


def prepare_capability_data(data: Any, config_dir: Path) -> Any:
    if not isinstance(data, dict):
        return data
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, dict):
        return data
    mcp_servers = capabilities.get("mcp_servers")
    skills = capabilities.get("skills")
    prepared_mcp_servers: list[Any] = []
    if isinstance(mcp_servers, list):
        for mcp in mcp_servers:
            if not isinstance(mcp, dict):
                prepared_mcp_servers.append(mcp)
                continue
            mcp_copy = dict(mcp)
            source_path = mcp_copy.get("source_path")
            if isinstance(source_path, str):
                path = Path(source_path).expanduser()
                if not path.is_absolute():
                    path = config_dir / path
                mcp_copy["source_path"] = str(path.resolve(strict=False))
            prepared_mcp_servers.append(mcp_copy)
    prepared_skills: list[Any] = []
    if isinstance(skills, list):
        for skill in skills:
            if not isinstance(skill, dict):
                prepared_skills.append(skill)
                continue
            skill_copy = dict(skill)
            source_path = skill_copy.get("source_path")
            if isinstance(source_path, str):
                path = Path(source_path).expanduser()
                if not path.is_absolute():
                    path = config_dir / path
                skill_copy["source_path"] = str(path.resolve(strict=False))
            prepared_skills.append(skill_copy)
    capabilities_copy = dict(capabilities)
    if isinstance(mcp_servers, list):
        capabilities_copy["mcp_servers"] = prepared_mcp_servers
    if isinstance(skills, list):
        capabilities_copy["skills"] = prepared_skills
    data_copy = dict(data)
    data_copy["capabilities"] = capabilities_copy
    return data_copy
