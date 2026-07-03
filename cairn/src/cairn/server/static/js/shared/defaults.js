import { LLM_EVENT_KIND_OPTIONS } from './constants.js';

export const defaultTaskCapabilities = () => ({
  mcp_server_ids: [],
  skill_ids: [],
  user_mcp_server_ids: [],
  user_skill_ids: [],
});

export const defaultTaskCapabilitiesMap = () => ({});

export const defaultAiProfileSelection = () => ({
  primary_profile_id: '',
  primary_model: '',
  primary_reasoning_type: '',
  fallback_profile_ids: [],
});

export const defaultTaskAiProfileSelections = () => ({});

export const defaultTaskTimeouts = () => ({
  bootstrap: { timeout: 300, conclude_timeout: 120 },
  explore: { timeout: 900, conclude_timeout: 180 },
  reason: { timeout: 300 },
});

export const defaultLlmVisibleEventKinds = () => LLM_EVENT_KIND_OPTIONS.filter(kind => kind !== 'usage');

export const baseCapabilityForm = () => ({
  kind: 'mcp_server',
  id: '',
  name: '',
  description: '',
  task_types: [],
  requires_ids: [],
  required_skill_ids: [],
  use_when: [],
  activation_hint: '',
  preferred_mcp_ids: [],
  transport: 'stdio',
  command: '',
  args: '',
  url: '',
  authorization_header: '',
  source_path: '',
  headers: {},
  probe_config: {},
  detail: '',
  available: true,
});
