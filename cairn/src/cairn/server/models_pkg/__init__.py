"""Domain-scoped Pydantic model modules."""

from __future__ import annotations

from cairn.server.models_pkg.capability_admin import CapabilityAdminRequest, CapabilityAdminResponse
from cairn.server.models_pkg.capability_catalog import (
    CapabilityCatalogItem,
    CapabilityHealthEntry,
    CapabilitySource,
    ProjectRole,
    ProjectRoleResponse,
    RoleCatalogItem,
    TaskCapabilities,
    TaskCapabilitiesMap,
    task_capabilities_map,
)
from cairn.server.models_pkg.capability_selection import (
    CapabilitySelection,
    ProjectCapabilitiesResponse,
    ProjectCapabilitiesUpdateRequest,
    ProjectCapabilitySnapshotItem,
    ProjectCapabilityTaskState,
    TaskCapabilitySelectionMap,
    task_capability_selection_map,
)
from cairn.server.models_pkg.intent_models import (
    ConcludeRequest,
    ConcludeResponse,
    CreateIntentRequest,
    HeartbeatRequest,
)
from cairn.server.models_pkg.project_requests import (
    CompleteRequest,
    CreateHintRequest,
    CreateProjectRequest,
    ReopenRequest,
    UpdateExecutionConfigRequest,
    UpdateProjectStatusRequest,
    UpdateProjectTitleRequest,
)
from cairn.server.models_pkg.project_responses import ReopenResponse
from cairn.server.models_pkg.reason_models import ReasonClaimRequest, ReasonFinishRequest
from cairn.server.models_pkg.replay_models import (
    ReplayRunAdvanceResponse,
    ReplayRunCreateRequest,
    ReplayRunCreateResponse,
)
from cairn.shared.contracts import ReasonState
