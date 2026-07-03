"""Wire contracts shared across Cairn processes.

Only models used across the server/dispatcher boundary belong here. Server-only
HTTP request/response DTOs stay in ``cairn.server.schemas``.
"""

from cairn.shared.contracts.ai_profiles import (
    CANONICAL_AUTH_ENV,
    AiProfile,
    AiProfileBase,
    HealthCheckItem,
    HealthCheckResult,
    ProjectAiProfileSnapshot,
    auth_env_warning,
    canonical_auth_env,
)
from cairn.shared.contracts.llm_events import (
    DEFAULT_LLM_HIDDEN_EVENT_KINDS,
    LLM_EVENT_KIND_OPTIONS,
    hidden_kinds_from_visible,
    normalize_llm_event_kinds,
    parse_llm_hidden_event_kinds,
    visible_kinds_from_hidden,
)
from cairn.shared.contracts.observability import ObservabilitySettings
from cairn.shared.contracts.projects import (
    Fact,
    Hint,
    Intent,
    IntentPhaseCheckpoint,
    ProjectDetail,
    ProjectGraphDelta,
    ProjectMeta,
    ProjectReason,
    ProjectSummary,
    ProjectSummaryPage,
    ProjectWorkSummary,
    ProjectWorkSummaryPage,
)
from cairn.shared.contracts.proxies import ProxyConfig, ProxySummary
from cairn.shared.contracts.reason import ReasonState
from cairn.shared.contracts.runtime_limits import ContainerLimits, RuntimeLimits
from cairn.shared.contracts.settings import Settings
from cairn.shared.contracts.system_config import ServerLogRetention, SystemSettingsAdmin
from cairn.shared.contracts.timeouts import BootstrapTaskTimeouts, ExploreTaskTimeouts, ReasonTaskTimeouts, TaskTimeouts
from cairn.shared.contracts.types import ReasoningType

__all__ = [
    "CANONICAL_AUTH_ENV",
    "DEFAULT_LLM_HIDDEN_EVENT_KINDS",
    "LLM_EVENT_KIND_OPTIONS",
    "AiProfile",
    "AiProfileBase",
    "BootstrapTaskTimeouts",
    "ExploreTaskTimeouts",
    "Fact",
    "HealthCheckItem",
    "HealthCheckResult",
    "Hint",
    "Intent",
    "IntentPhaseCheckpoint",
    "ObservabilitySettings",
    "ContainerLimits",
    "RuntimeLimits",
    "ProjectAiProfileSnapshot",
    "ProjectDetail",
    "ProjectGraphDelta",
    "ProjectMeta",
    "ProjectReason",
    "ProjectSummary",
    "ProjectSummaryPage",
    "ProjectWorkSummary",
    "ProjectWorkSummaryPage",
    "ProxyConfig",
    "ProxySummary",
    "ReasonState",
    "ReasonTaskTimeouts",
    "ReasoningType",
    "ServerLogRetention",
    "Settings",
    "SystemSettingsAdmin",
    "TaskTimeouts",
    "auth_env_warning",
    "canonical_auth_env",
    "hidden_kinds_from_visible",
    "normalize_llm_event_kinds",
    "parse_llm_hidden_event_kinds",
    "visible_kinds_from_hidden",
]
