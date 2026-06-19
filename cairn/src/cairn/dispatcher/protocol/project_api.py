from __future__ import annotations

from pydantic import TypeAdapter

from cairn.dispatcher.protocol.base import HttpClientBase
from cairn.dispatcher.protocol.results import ApiResult
from cairn.shared.contracts import (
    ProjectDetail,
    ProjectSummary,
    ProjectWorkSummary,
    ProxyConfig,
    Settings,
    SystemSettingsAdmin,
)

_PROJECT_SUMMARY_ADAPTER = TypeAdapter(list[ProjectSummary])
_PROJECT_WORK_SUMMARY_ADAPTER = TypeAdapter(list[ProjectWorkSummary])


class ProjectApiClient(HttpClientBase):
    def list_projects(self) -> list[ProjectSummary]:
        response = self._get("/projects")
        response.raise_for_status()
        return _PROJECT_SUMMARY_ADAPTER.validate_python(response.json())

    def list_project_work(self) -> list[ProjectWorkSummary]:
        response = self._get("/projects/work")
        response.raise_for_status()
        return _PROJECT_WORK_SUMMARY_ADAPTER.validate_python(response.json())

    def get_project(self, project_id: str) -> ProjectDetail:
        response = self._get(f"/projects/{project_id}")
        response.raise_for_status()
        return ProjectDetail.model_validate(response.json())

    def get_settings(self) -> Settings:
        response = self._get("/system-settings")
        response.raise_for_status()
        return Settings.model_validate(SystemSettingsAdmin.model_validate(response.json()).settings)

    def get_proxy(self, proxy_id: str) -> ProxyConfig:
        response = self._get(f"/proxies/{proxy_id}")
        if response.status_code == 404:
            raise LookupError(f"proxy not found: {proxy_id}")
        response.raise_for_status()
        return ProxyConfig.model_validate(response.json())

    def export_project(self, project_id: str) -> str:
        response = self._get(f"/projects/{project_id}/export", params={"format": "yaml"})
        response.raise_for_status()
        return response.text

    def get_project_execution_config(self, project_id: str, task_type: str) -> ApiResult:
        return self._get_json_result(f"/projects/{project_id}/execution-configs/{task_type}")
