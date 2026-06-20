"""Server-private HTTP request/response Pydantic models.

Models in this package belong to the FastAPI server surface only. Put DTOs
shared with the dispatcher or other processes in ``cairn.shared.contracts``
instead, and keep pure business decisions in domain/application code.
"""

from __future__ import annotations

from cairn.server.schemas.capability_admin import (
    CapabilityAdminRequest,
    CapabilityAdminResponse,
    McpImportRequest,
    McpImportResponse,
)
from cairn.server.schemas.capability_catalog import (
    CapabilityCatalogItem,
    CapabilityHealthEntry,
    CapabilitySource,
    ProjectRole,
    ProjectRoleResponse,
    RoleDefaultSkillsUpdate,
    RoleCatalogItem,
    TaskCapabilities,
    TaskCapabilitiesMap,
    task_capabilities_map,
)
from cairn.server.schemas.capability_selection import (
    CapabilitySelection,
    ProjectCapabilitiesResponse,
    ProjectCapabilitiesUpdateRequest,
    ProjectCapabilitySnapshotItem,
    ProjectCapabilityTaskState,
    TaskCapabilitySelectionMap,
    task_capability_selection_map,
)
from cairn.server.schemas.intent_models import (
    ConcludeRequest,
    ConcludeResponse,
    CreateIntentRequest,
    HeartbeatRequest,
)
from cairn.server.schemas.project_requests import (
    CompleteRequest,
    CreateHintRequest,
    CreateProjectRequest,
    ReopenRequest,
    UpdateProjectStatusRequest,
    UpdateProjectTitleRequest,
)
from cairn.server.schemas.project_responses import ProjectPollStateResponse, ReopenResponse
from cairn.server.schemas.reason_models import ReasonClaimRequest, ReasonFinishRequest
from cairn.server.schemas.replay_models import (
    ReplayRunAdvanceResponse,
    ReplayRunCreateRequest,
    ReplayRunCreateResponse,
)
from cairn.shared.contracts import ReasonState
