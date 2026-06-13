from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cairn.shared.config.capability_models import CapabilitiesConfig
from cairn.shared.config.remote_support_models import RemoteSupportConfig
from cairn.shared.config.role_models import RoleConfig


class ResourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    remote_support: RemoteSupportConfig = Field(default_factory=RemoteSupportConfig)
    capabilities: CapabilitiesConfig = Field(default_factory=CapabilitiesConfig)
    roles: list[RoleConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_role_ids(self) -> ResourceConfig:
        role_ids = [role.id for role in self.roles]
        if len(role_ids) != len(set(role_ids)):
            raise ValueError("roles ids must be unique")
        return self
