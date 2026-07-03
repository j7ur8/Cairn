from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cairn.shared.config.capability_models import CapabilitiesConfig
from cairn.shared.config.role_models import RoleConfig
from cairn.shared.config.server_models import ServerResourceConfig


class ResourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    servers: list[ServerResourceConfig] = Field(default_factory=list)
    capabilities: CapabilitiesConfig = Field(default_factory=CapabilitiesConfig)
    roles: list[RoleConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ids(self) -> ResourceConfig:
        server_ids = [server.id for server in self.servers]
        if len(server_ids) != len(set(server_ids)):
            raise ValueError("servers ids must be unique")
        role_ids = [role.id for role in self.roles]
        if len(role_ids) != len(set(role_ids)):
            raise ValueError("roles ids must be unique")
        return self
