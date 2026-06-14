const ALL_LLM_EXECUTIONS_VALUE = '__all__';
const defaultTaskCapabilities = () => ({
  mcp_server_ids: [],
  skill_ids: [],
  user_mcp_server_ids: [],
  user_skill_ids: [],
});
const defaultTaskCapabilitiesMap = () => ({
});
const defaultAiProfileSelection = () => ({
  primary_profile_id: '',
  primary_model: '',
  primary_reasoning_type: '',
  fallback_profile_ids: [],
});
const defaultTaskAiProfileSelections = () => ({
});
const defaultTaskTimeouts = () => ({
  bootstrap: { timeout: 300, conclude_timeout: 90 },
  explore: { timeout: 300, conclude_timeout: 90 },
  reason: { timeout: 300 },
});
const defaultLlmVisibleEventKinds = () => LLM_EVENT_KIND_OPTIONS.filter(kind => kind !== 'usage');
const defaultCapabilityForm = () => ({
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
