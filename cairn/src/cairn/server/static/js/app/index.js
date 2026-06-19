import { ALL_LLM_EXECUTIONS_VALUE } from '../shared/constants.js';
import { createAppState } from './create-app-state.js';
import { createCoreState } from './state.core.js';
import { createSettingsState } from './state.settings.js';
import { createSettingsAdminState } from './state.settings_admin.js';
import { createPromptsState } from './state.prompts.js';
import { createAiProfilesState } from './state.ai_profiles.js';
import { createProxiesState } from './state.proxies.js';
import { createWorkspaceUiState } from '../workspace/state.ui.js';
import { createWorkspaceGraphState } from '../workspace/state.graph.js';
import { createWorkspaceLogState } from '../workspace/state.llm_log.js';
import { createWorkspaceProjectsState } from '../workspace/state.projects.js';
import { createWorkspaceCapabilitiesState } from '../workspace/state.capabilities.js';

window.ALL_LLM_EXECUTIONS_VALUE = ALL_LLM_EXECUTIONS_VALUE;
window.cairnApp = function cairnApp() {
  return createAppState(
    createCoreState(),
    createWorkspaceGraphState(),
    createWorkspaceLogState(),
    createWorkspaceProjectsState(),
    createSettingsState(),
    createSettingsAdminState(),
    createPromptsState(),
    createAiProfilesState(),
    createProxiesState(),
    createWorkspaceCapabilitiesState(),
    createWorkspaceUiState(),
  );
};
