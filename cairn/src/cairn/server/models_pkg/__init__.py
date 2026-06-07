"""Pydantic models for the Cairn server, organized by concern.

The historical ``cairn/server/models.py`` was a single 900-line file
that mixed project, intent, capability, role, proxy, and AI profile
schemas. This package is the post-split home: each submodule owns
one concern, and this ``__init__`` re-exports every public symbol
so existing ``from cairn.server.models import X`` imports keep
working unchanged.
"""
from __future__ import annotations

from pydantic import BaseModel

# Re-export order matches the previous single-file layout so
# debugging stack traces stay readable.
from cairn.server.models_pkg.common import (  # noqa: F401
    ReasoningType,
    Settings,
)
from cairn.server.models_pkg.projects import (  # noqa: F401
    CreateHintInline,
    AttachmentUpload,
    AttachmentUploadResponse,
    Fact,
    Hint,
    ProjectDetail,
    ProjectFileItem,
    ProjectFilesResponse,
    ProjectMeta,
    ProjectReason,
    ProjectSummary,
)
from cairn.server.models_pkg.intents import (  # noqa: F401
    CapabilitySelection,
    CompleteRequest,
    ConcludeRequest,
    ConcludeResponse,
    CreateHintRequest,
    CreateIntentRequest,
    CreateProjectRequest,
    HeartbeatRequest,
    ProjectRoleSelection,
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
    CapabilityCatalogItem,
    ProjectCapabilitiesResponse,
    ProjectRole,
    ProjectRoleResponse,
    RegisterCapabilityCatalogRequest,
    RegisterRoleCatalogItem,
    RegisterRoleCatalogRequest,
    RoleCatalogItem,
    CapabilityAdminRequest,
    CapabilityAdminResponse,
    CapabilityCatalogItem,
    CapabilityHealthEntry,
    CapabilitySource,
    ProjectCapabilitiesResponse,
    ProjectCapabilitiesUpdateRequest,
    ProjectRole,
    ProjectRoleResponse,
    RegisterCapabilityCatalogRequest,
    RegisterRoleCatalogItem,
    RegisterRoleCatalogRequest,
    RoleCatalogItem,
    TaskCapabilities,
    TaskCapabilitiesMap,
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
    CANONICAL_AUTH_ENV,
    AiProfileBase,
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
    HealthCheckItem,
    HealthCheckResult,
    ProjectAiProfileSnapshot,
    ProjectAiProfilesResponse,
    TaskAiProfileSelections,
    canonical_auth_env,
    auth_env_warning,
)


# Forward references resolved after every submodule has been imported.
# Several request / response models reference types from sibling
# modules while ``from __future__ import annotations`` stringifies
# those annotations. Rebuild them after the full public surface is
# imported so undefined refs fail at import time instead of at the
# first endpoint response.
from cairn.server.models_pkg.intents import (  # noqa: E402
    ConcludeResponse,
    CreateProjectRequest,
    ReopenResponse,
    ReplayRunCreateRequest,
    ReplayRunCreateResponse,
)
from cairn.server.models_pkg.ai_profiles import AiProfileSyncRequest, AiProfileSyncWorker  # noqa: E402

for _model in (
    CreateProjectRequest,
    ReplayRunCreateRequest,
    ConcludeResponse,
    ReopenResponse,
    ReplayRunCreateResponse,
    AiProfileSyncRequest,
    AiProfileSyncWorker,
):
    _model.model_rebuild(raise_errors=True)
# ``ReasoningType`` lives in common.py; the AiProfile* classes
# reference it under ``from __future__ import annotations`` so
# Pydantic has to resolve the type after every submodule has been
# imported. Rebuild every model in ai_profiles.py that touches the
# type, plus the snapshot / selection classes that hold an
# ``AiProfile`` reference.
import cairn.server.models_pkg.ai_profiles as _ai  # noqa: E402
import cairn.server.models_pkg.intents as _int  # noqa: E402
import cairn.server.models_pkg.projects as _prj  # noqa: E402
import cairn.server.models_pkg.capabilities as _cap  # noqa: E402
import cairn.server.models_pkg.proxies as _prx  # noqa: E402

# Rebuild every BaseModel in the package. Forward references between
# submodules (ReasoningType, ProxySummary, AiProfileSelection, etc.)
# are stringified by ``from __future__ import annotations`` and only
# resolve after every submodule has been imported.
for _mod in (_ai, _int, _prj, _cap, _prx):
    for _name in dir(_mod):
        _obj = getattr(_mod, _name)
        if isinstance(_obj, type) and issubclass(_obj, BaseModel) and _obj is not BaseModel:
            _obj.model_rebuild(raise_errors=True)
