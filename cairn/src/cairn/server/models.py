"""Backwards-compatible re-export of the Pydantic models package.

The historical ``cairn.server.models`` module was a single 900-line
file. It is now split into ``cairn.server.models_pkg.*``; this
shim re-exports every public symbol so the existing import sites
(``from cairn.server.models import AiProfile`` etc.) keep working
without churn.
"""
from __future__ import annotations

# Import every submodule's public surface explicitly. Using ``import *``
# is fragile because it depends on each submodule setting ``__all__``;
# listing the names directly keeps the shim robust to accidental
# additions to the submodules and gives a clear error when a new
# public class is added but not re-exported here.
from cairn.server.models_pkg.common import (  # noqa: F401
    ReasoningType,
    Settings,
)
from cairn.server.models_pkg.projects import (  # noqa: F401
    AttachmentUpload,
    AttachmentUploadResponse,
    CreateHintInline,
    Fact,
    Hint,
    Intent,
    ProjectDetail,
    ProjectFileItem,
    ProjectFilesResponse,
    ProjectMeta,
    ProjectReason,
    ProjectSummary,
)
from cairn.server.models_pkg.intents import (  # noqa: F401
    CompleteRequest,
    ConcludeRequest,
    ConcludeResponse,
    CreateHintRequest,
    CreateIntentRequest,
    CreateProjectRequest,
    HeartbeatRequest,
    ReasonClaimRequest,
    ReasonFinishRequest,
    ReasonState,
    ReopenRequest,
    ReopenResponse,
    ReplayRunAdvanceResponse,
    ReplayRunCreateRequest,
    ReplayRunCreateResponse,
    UpdateProjectStatusRequest,
    UpdateProjectTitleRequest,
)
from cairn.server.models_pkg.capabilities import (  # noqa: F401
    CapabilityAdminRequest,
    CapabilityAdminResponse,
    CapabilityCatalogItem,
    CapabilityHealthEntry,
    CapabilitySelection,
    CapabilitySource,
    ProjectCapabilitiesResponse,
    ProjectCapabilitiesUpdateRequest,
    ProjectCapabilitySnapshotItem,
    ProjectCapabilityTaskState,
    ProjectRole,
    ProjectRoleResponse,
    RegisterCapabilityCatalogRequest,
    RegisterRoleCatalogItem,
    RegisterRoleCatalogRequest,
    RoleCatalogItem,
    TaskCapabilitySelectionMap,
    TaskCapabilities,
    TaskCapabilitiesMap,
    task_capability_selection_map,
    task_capabilities_map,
)
from cairn.server.models_pkg.proxies import (  # noqa: F401
    ProxyConfig,
    ProxyCreate,
    ProxySummary,
    ProxyUpdate,
)
from cairn.server.models_pkg.ai_profiles import (  # noqa: F401
    AiProfile,
    AiProfileBase,
    AiProfileCheckCompleteRequest,
    AiProfileCheckRequest,
    AiProfileCheckTriggerResponse,
    AiProfileCreate,
    AiProfileHealthReport,
    AiProfileHealthReportRequest,
    AiProfileModelsReport,
    AiProfileModelsReportRequest,
    AiProfileSelection,
    AiProfileSyncRequest,
    AiProfileSyncWorker,
    AiProfileUpdate,
    AiProfileWithHealth,
    AiWorkerType,
    CANONICAL_AUTH_ENV,
    HealthCheckItem,
    HealthCheckResult,
    ProjectAiProfileSnapshot,
    ProjectAiProfilesResponse,
    TaskAiProfileSelections,
    canonical_auth_env,
    auth_env_warning,
)
