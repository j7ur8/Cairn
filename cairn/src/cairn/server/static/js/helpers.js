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
window.SETTINGS_UI_CLASSES = Object.freeze({
  primaryButton: 'h-7 inline-flex items-center justify-center px-3 text-xs rounded-lg bg-brand-500 text-white font-medium hover:bg-brand-600 transition disabled:opacity-40 disabled:cursor-not-allowed',
  secondaryButton: 'h-7 inline-flex items-center justify-center px-3 text-xs rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 transition disabled:opacity-40 disabled:cursor-not-allowed',
  panel: 'rounded-xl border border-slate-200 bg-slate-50/60 p-3',
  card: 'rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm',
  compactCard: 'rounded-xl border border-slate-200 bg-white px-3 py-2',
  fieldInput: 'px-3 py-1.5 border border-slate-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-400 transition placeholder:text-slate-300',
});
