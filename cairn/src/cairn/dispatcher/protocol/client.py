from __future__ import annotations

from cairn.dispatcher.protocol.ai_profile_api import AiProfileApiClient
from cairn.dispatcher.protocol.observability_api import ObservabilityApiClient
from cairn.dispatcher.protocol.project_api import ProjectApiClient
from cairn.dispatcher.protocol.results import ApiResult, ProtocolError
from cairn.dispatcher.protocol.task_api import TaskApiClient


class CairnClient(
    ProjectApiClient,
    TaskApiClient,
    AiProfileApiClient,
    ObservabilityApiClient,
):
    pass


__all__ = ["ApiResult", "CairnClient", "ProtocolError"]
