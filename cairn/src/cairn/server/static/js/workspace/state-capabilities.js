import { baseCapabilityForm, defaultTaskAiProfileSelections, defaultTaskCapabilitiesMap, defaultTaskTimeouts } from '../shared/defaults.js';
import { selectedCapabilitiesForPayload } from '../shared/capability-selection.js';
import {
  jsonObjectToText,
  keyValueObjectToText,
  normalizeStringList,
  textToJsonObject,
  textToKeyValueObject,
} from '../shared/form.js';

export function createWorkspaceCapabilitiesState() {
  return {
    capabilities: {
      catalog: [],
      tasks: defaultTaskCapabilitiesMap(),
      health: {},
      unavailable: { mcp_server_ids: [], skill_ids: [] },
      projectAiProfiles: { catalog: [], selections: defaultTaskAiProfileSelections(), snapshots: [], unavailable_profile_ids: [] },
    },
    capabilityAdmin: { catalog: [], health: {} },
    capabilityForm: baseCapabilityForm(),
    capabilityFormOpen: false,
    capabilityEditId: '',
    capabilityImportOpen: false,
    capabilityImportText: '',
    capabilitySearch: { mcp: '', skill: '' },
    capabilityProbeBusy: {},
    capabilityProbeAllBusy: false,
    capabilitiesSaving: false,
    newProjectCapabilityPanel: 'bootstrap',
    replayConfigCapabilityPanel: 'bootstrap',

    async loadTaskTypes() {
      const rows = await this.api('GET', '/task-types') || [];
      this.task_type_specs = Array.isArray(rows) ? rows : [];
      this.task_types = this.task_type_specs
        .map(item => item && typeof item.name === 'string' ? item.name.trim() : '')
        .filter(Boolean);
      this.newProject.capabilities = this.defaultTaskCapabilitiesMap();
      this.newProject.ai_profiles = this.defaultTaskAiProfileSelections();
      if (this.capabilityForm && (!Array.isArray(this.capabilityForm.task_types) || this.capabilityForm.task_types.length === 0)) {
        this.capabilityForm.task_types = [...this.task_types];
      }
    },

    async loadCapabilities() {
      if (!this.selectedProjectId) return;
      try {
        const [data, aiData] = await Promise.all([
          this.api('GET', `/projects/${this.selectedProjectId}/capabilities`),
          this.loadProjectAiProfiles(this.selectedProjectId).catch(() => null),
        ]);
        this.capabilities = {
          catalog: data.catalog || [],
          tasks: this.taskCapabilitiesFromServerTasks(data.tasks),
          health: data.health || {},
          unavailable: data.unavailable || { mcp_server_ids: [], skill_ids: [] },
          projectAiProfiles: aiData || { catalog: [], selections: this.defaultTaskAiProfileSelections(), snapshots: [], unavailable_profile_ids: [] },
        };
      } catch (e) {
        console.error(e);
        this.capabilities = {
          catalog: [],
          tasks: this.defaultTaskCapabilitiesMap(),
          health: {},
          unavailable: { mcp_server_ids: [], skill_ids: [] },
          projectAiProfiles: { catalog: [], selections: this.defaultTaskAiProfileSelections(), snapshots: [], unavailable_profile_ids: [] },
        };
      }
    },

    async saveCapabilities() {
      if (!this.selectedProjectId) return;
      try {
        if (!this.capabilities?.tasks) return;
        const body = { capabilities: this.selectedCapabilitiesForPayload(this.capabilities.tasks) };
        const data = await this.api('PUT', `/projects/${this.selectedProjectId}/capabilities`, body);
        this.capabilities = {
          ...this.capabilities,
          catalog: data.catalog || [],
          tasks: this.taskCapabilitiesFromServerTasks(data.tasks),
          health: data.health || {},
          unavailable: data.unavailable || { mcp_server_ids: [], skill_ids: [] },
        };
        this.showToast('Capabilities saved');
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    newProjectAiProfileItems() {
      return (this.aiProfiles || []).filter(item => item.available !== false);
    },

    aiReasoningTypeOptions() {
      return ['low', 'medium', 'high', 'xhigh'];
    },

    aiProfileModelOptions(profile) {
      if (!profile) return [];
      const values = [profile.model, ...((profile.models || []))].filter(Boolean);
      return [...new Set(values)];
    },

    defaultCapabilityForm() {
      return {
        kind: 'mcp_server',
        id: '',
        name: '',
        description: '',
        task_types: [...this.task_types],
        requires_ids: [],
        required_skill_ids: [],
        use_when: [],
        use_when_text: '',
        activation_hint: '',
        preferred_mcp_ids: [],
        transport: 'stdio',
        command: '',
        args: '',
        url: '',
        authorization_header: '',
        source_path: '',
        env_text: '',
        headers: {},
        headers_text: '',
        probe_config: {},
        probe_config_text: '{}',
        detail: '',
        available: true,
      };
    },

    openCreateCapability(kind = 'mcp_server') {
      if (kind === 'skill') return this.openCreateSkill();
      return this.openCreateMcpServer();
    },

    openCreateMcpServer() {
      this.capabilityEditId = '';
      this.capabilityForm = this.defaultCapabilityForm();
      this.capabilityForm.kind = 'mcp_server';
      this.capabilityFormOpen = true;
      this.capabilityImportOpen = false;
    },

    openCreateSkill() {
      this.capabilityEditId = '';
      this.capabilityForm = this.defaultCapabilityForm();
      this.capabilityForm.kind = 'skill';
      this.capabilityFormOpen = true;
      this.capabilityImportOpen = false;
    },

    cancelCapabilityEdit() {
      this.capabilityEditId = '';
      this.capabilityForm = this.defaultCapabilityForm();
      this.capabilityFormOpen = false;
    },

    openImportMcpJson() {
      this.cancelCapabilityEdit();
      this.capabilityImportOpen = true;
      this.capabilityImportText = this.capabilityImportText || '{\n  "mcpServers": {\n  }\n}';
    },

    cancelImportMcpJson() {
      this.capabilityImportOpen = false;
      this.capabilityImportText = '';
    },

    openEditCapability(item) {
      this.capabilityEditId = item.id;
      this.capabilityForm = {
        kind: item.kind,
        id: item.id,
        name: item.name,
        description: item.description || '',
        task_types: Array.isArray(item.task_types) ? [...item.task_types] : [],
        requires_ids: Array.isArray(item.requires_ids) ? [...item.requires_ids] : [],
        required_skill_ids: Array.isArray(item.required_skill_ids) ? [...item.required_skill_ids] : [],
        use_when: Array.isArray(item.use_when) ? [...item.use_when] : [],
        use_when_text: Array.isArray(item.use_when) ? item.use_when.join('\n') : '',
        activation_hint: item.activation_hint || '',
        preferred_mcp_ids: Array.isArray(item.preferred_mcp_ids) ? [...item.preferred_mcp_ids] : [],
        transport: item.transport,
        command: item.command || '',
        args: Array.isArray(item.args) ? item.args.join('\n') : (item.args || ''),
        url: item.url || '',
        source_path: item.source_path || '',
        env: (item.env && typeof item.env === 'object') ? item.env : {},
        env_text: this.keyValueObjectToText(item.env || {}),
        headers: (item.headers && typeof item.headers === 'object') ? item.headers : {},
        headers_text: this.keyValueObjectToText(item.headers || {}),
        authorization_header: item.headers && typeof item.headers === 'object' ? (item.headers.Authorization || '') : '',
        probe_config: (item.probe_config && typeof item.probe_config === 'object') ? item.probe_config : {},
        probe_config_text: this.jsonObjectToText(item.probe_config || {}),
        detail: item.detail || '',
        available: item.available !== false,
      };
      this.capabilityFormOpen = true;
    },

    async saveCapability() {
      if (!this.capabilityForm.id.trim() || !this.capabilityForm.name.trim()) {
        this.showToast('id and name are required', 'error');
        return;
      }
      const basePayload = {
        kind: this.capabilityForm.kind,
        id: this.capabilityForm.id.trim(),
        name: this.capabilityForm.name.trim(),
        description: this.capabilityForm.description || '',
        task_types: normalizeStringList(this.capabilityForm.task_types),
        requires_ids: normalizeStringList(this.capabilityForm.requires_ids),
        required_skill_ids: normalizeStringList(this.capabilityForm.required_skill_ids),
        use_when: normalizeStringList(this.capabilityForm.use_when_text || this.capabilityForm.use_when),
        activation_hint: this.capabilityForm.activation_hint || '',
        preferred_mcp_ids: normalizeStringList(this.capabilityForm.preferred_mcp_ids),
        detail: this.capabilityForm.detail || '',
        available: this.capabilityForm.available !== false,
      };
      let payload;
      if (this.capabilityForm.kind === 'mcp_server') {
        payload = {
          ...basePayload,
          transport: this.capabilityForm.transport,
          command: this.capabilityForm.command || '',
          args: normalizeStringList(this.capabilityForm.args),
          url: this.capabilityForm.url || '',
          source_path: this.capabilityForm.source_path || '',
        };
        payload.env = this.textToKeyValueObject(this.capabilityForm.env_text || '');
        payload.headers = this.textToKeyValueObject(this.capabilityForm.headers_text || '');
        if (this.capabilityForm.authorization_header) {
          payload.headers.Authorization = this.capabilityForm.authorization_header;
        } else {
          delete payload.headers.Authorization;
        }
        payload.probe_config = this.textToJsonObject(this.capabilityForm.probe_config_text || '{}');
      } else {
        payload = {
          ...basePayload,
          source_path: this.capabilityForm.source_path || '',
        };
      }
      try {
        await this.api('PUT', `/capabilities/admin/${payload.kind}/${encodeURIComponent(payload.id)}`, payload);
        this.showToast('Capability saved');
        this.cancelCapabilityEdit();
        await this.loadCapabilityAdmin();
        await this.loadNewProjectCatalog();
        await this.loadCapabilities();
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async importMcpJson() {
      let payload;
      try {
        payload = JSON.parse(this.capabilityImportText || '{}');
      } catch (e) {
        this.showToast(`Invalid JSON: ${e.message}`, 'error');
        return;
      }
      try {
        const result = await this.api('POST', '/capabilities/admin/mcp/import-json', payload);
        const created = (result.created || []).length;
        const updated = (result.updated || []).length;
        const conflicts = (result.conflicts || []).length;
        this.showToast(`Imported MCP: ${created} created, ${updated} updated${conflicts ? `, ${conflicts} conflicts` : ''}`);
        this.cancelImportMcpJson();
        await this.loadCapabilityAdmin();
        await this.loadNewProjectCatalog();
        await this.loadCapabilities();
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async deleteCapabilityAdmin(kind, id, name) {
      const ok = window.confirm(`Delete ${kind} "${name}"? Existing project snapshots are preserved, but the capability can no longer be selected.`);
      if (!ok) return;
      try {
        await this.api('DELETE', `/capabilities/admin/${kind}/${encodeURIComponent(id)}`);
        this.showToast('Capability deleted');
        await this.loadCapabilityAdmin();
        await this.loadNewProjectCatalog();
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async probeCapabilityAdmin(kind, id) {
      const key = `${kind}:${id}`;
      this.capabilityProbeBusy = { ...this.capabilityProbeBusy, [key]: true };
      try {
        const path = kind === 'mcp_server'
          ? `/capabilities/admin/mcp_server/${encodeURIComponent(id)}/probe`
          : `/capabilities/admin/${kind}/${encodeURIComponent(id)}/probe`;
        const entry = await this.api('POST', path, {});
        this.showToast(`Probe ${entry.status}: ${entry.message || 'ok'}`);
        await this.loadCapabilityAdmin();
      } catch (e) {
        this.showToast(e.message, 'error');
      } finally {
        const next = { ...this.capabilityProbeBusy };
        delete next[key];
        this.capabilityProbeBusy = next;
      }
    },

    async probeAllMcpCapabilities() {
      this.capabilityProbeAllBusy = true;
      try {
        const results = await this.api('POST', '/capabilities/admin/mcp/probe-all', {});
        const ok = (results || []).filter(item => item.status === 'ok').length;
        const failed = (results || []).length - ok;
        this.showToast(`MCP probe complete: ${ok} ok, ${failed} failed`);
        await this.loadCapabilityAdmin();
      } catch (e) {
        this.showToast(e.message, 'error');
      } finally {
        this.capabilityProbeAllBusy = false;
      }
    },

    capabilityProbeBusyFor(kind, id) {
      return !!this.capabilityProbeBusy[`${kind}:${id}`] || (kind === 'mcp_server' && this.capabilityProbeAllBusy);
    },

    async loadCapabilityAdmin() {
      try {
        const data = await this.api('GET', '/capabilities/admin');
        this.capabilityAdmin = { catalog: data.catalog || [], health: data.health || {} };
      } catch (e) {
        this.capabilityAdmin = { catalog: [], health: {} };
      }
    },

    capabilityItems(kind) {
      const query = (kind === 'mcp_server' ? this.capabilitySearch.mcp : this.capabilitySearch.skill || '').toLowerCase();
      const items = (this.capabilityAdmin.catalog || []).filter(item => item.kind === kind);
      if (!query) return items;
      return items.filter(item => [
        item.id,
        item.name,
        item.description,
        item.transport,
        item.source_path,
        item.command,
        item.url,
      ].some(value => String(value || '').toLowerCase().includes(query)));
    },

    capabilityDependencyOptions(kind) {
      return (this.capabilityAdmin.catalog || []).filter(item => item.kind === kind && item.id !== this.capabilityForm.id);
    },

    toggleCapabilityListField(field, id, checked) {
      const current = Array.isArray(this.capabilityForm[field]) ? this.capabilityForm[field] : [];
      const set = new Set(current);
      if (checked) set.add(id);
      else set.delete(id);
      this.capabilityForm[field] = Array.from(set);
    },

    keyValueObjectToText(value) {
      return keyValueObjectToText(value);
    },

    textToKeyValueObject(text) {
      return textToKeyValueObject(text);
    },

    jsonObjectToText(value) {
      return jsonObjectToText(value);
    },

    textToJsonObject(text) {
      return textToJsonObject(text);
    },

    aiProfileTaskTypes() {
      return this.task_types.map(key => ({ key, label: this.taskTypeLabel(key) }));
    },

    capabilityTaskTypes() {
      return this.task_types.map(key => ({ key, label: this.taskTypeLabel(key) }));
    },

    defaultTaskCapabilities() {
      return { mcp_server_ids: [], skill_ids: [], user_mcp_server_ids: [], user_skill_ids: [] };
    },

    defaultTaskCapabilitiesMap() {
      const out = {};
      for (const task of this.capabilityTaskTypes()) {
        out[task.key] = this.defaultTaskCapabilities();
      }
      return out;
    },

    ensureTaskCapabilitiesMap(target) {
      const key = target === this.capabilities ? 'tasks' : 'capabilities';
      if (!target[key]) {
        target[key] = this.defaultTaskCapabilitiesMap();
      }
      for (const task of this.capabilityTaskTypes()) {
        if (!target[key][task.key]) {
          target[key][task.key] = this.defaultTaskCapabilities();
        }
        const entry = target[key][task.key];
        for (const field of ['mcp_server_ids', 'skill_ids', 'user_mcp_server_ids', 'user_skill_ids']) {
          if (!Array.isArray(entry[field])) entry[field] = [];
        }
      }
      return target[key];
    },

    taskCapabilitiesFromServerTasks(tasks) {
      const out = this.defaultTaskCapabilitiesMap();
      const source = tasks && typeof tasks === 'object' ? tasks : {};
      for (const task of this.capabilityTaskTypes()) {
        const state = source[task.key] || {};
        const selected = state.selected || {};
        const snapshots = Array.isArray(state.snapshots) ? state.snapshots : [];
        const mcp = snapshots.filter(item => item.kind === 'mcp_server').map(item => item.capability_id);
        const skills = snapshots.filter(item => item.kind === 'skill').map(item => item.capability_id);
        out[task.key] = {
          mcp_server_ids: [...new Set(mcp)],
          skill_ids: [...new Set(skills)],
          user_mcp_server_ids: [...new Set(selected.mcp_server_ids || [])],
          user_skill_ids: this.sanitizeUserSkillIdsForProjectPayload(selected.skill_ids || []),
        };
      }
      return out;
    },

    capabilitiesForTask(task, items) {
      const catalog = items || this.capabilities?.catalog || [];
      return catalog.filter(item => Array.isArray(item.task_types) && item.task_types.includes(task));
    },

    selectableCapabilitiesForTask(task, items) {
      const hiddenSkillIds = new Set(this.roleDefaultTopLevelSkillIds());
      return this.capabilitiesForTask(task, items).filter(item => item.kind !== 'skill' || !hiddenSkillIds.has(item.id));
    },

    userCapabilitySelected(task, kind, id) {
      const perTask = this.ensureTaskCapabilitiesMap(this._activeCapabilitiesTarget());
      const field = kind === 'mcp_server' ? 'user_mcp_server_ids' : 'user_skill_ids';
      return (perTask[task]?.[field] || []).includes(id);
    },

    effectiveCapabilitySelected(task, kind, id) {
      const perTask = this.ensureTaskCapabilitiesMap(this._activeCapabilitiesTarget());
      const field = kind === 'mcp_server' ? 'mcp_server_ids' : 'skill_ids';
      return (perTask[task]?.[field] || []).includes(id);
    },

    toggleUserCapability(task, kind, id, checked) {
      const perTask = this.ensureTaskCapabilitiesMap(this._activeCapabilitiesTarget());
      const entry = perTask[task];
      const userField = kind === 'mcp_server' ? 'user_mcp_server_ids' : 'user_skill_ids';
      const userSet = new Set(entry[userField] || []);
      if (checked) userSet.add(id);
      else userSet.delete(id);
      entry[userField] = Array.from(userSet);
      this._expandRequiresForTask(task, kind, id, checked);
      this._refreshEffectiveTask(task);
    },

    _activeCapabilitiesTarget() {
      if (this.showReplayConfigModal) return this.replayConfig;
      if (this.showNewProject) return this.newProject;
      if (this.selectedProjectId) return this.capabilities;
      return this.newProject;
    },

    capabilityTaskHealthStatus(task) {
      const entries = (this.capabilities?.health || {})[task] || [];
      if (entries.length === 0) return 'ok';
      if (entries.some(entry => entry.status === 'error')) return 'error';
      if (entries.some(entry => entry.status === 'warn')) return 'warn';
      return 'ok';
    },

    capabilityHealthStatus(item) {
      if (item.last_probe_status) return item.last_probe_status;
      return item.available ? 'ok' : 'warn';
    },

    capabilityHealthDotClass(item) {
      const status = this.capabilityHealthStatus(item);
      if (status === 'error') return 'bg-rose-500';
      if (status === 'warn') return 'bg-amber-500';
      return 'bg-emerald-500';
    },

    capabilityHealthTitle(item) {
      if (item.last_probe_status) {
        return `Last probe @ ${item.last_probe_at || '-'}: ${item.last_probe_status}${item.last_probe_message ? ' - ' + item.last_probe_message : ''}`;
      }
      return item.available ? 'available' : 'unavailable';
    },

    capabilitiesForNewProject() {
      if (!this.newProject.capabilities) {
        this.newProject.capabilities = this.defaultTaskCapabilitiesMap();
      }
      return this.selectedCapabilitiesForPayload(this.newProject.capabilities);
    },

    capabilitiesForReplayRun() {
      if (!this.replayConfig.capabilities) {
        this.replayConfig.capabilities = this.defaultTaskCapabilitiesMap();
      }
      return this.selectedCapabilitiesForPayload(this.replayConfig.capabilities);
    },

    selectedCapabilitiesForPayload(capabilities) {
      return selectedCapabilitiesForPayload(
        capabilities,
        this.capabilityTaskTypes(),
        () => this.defaultTaskCapabilities(),
        this.roleDefaultTopLevelSkillIds(),
      );
    },

    hydrateReplayCapabilitiesFromSource(projectCapabilities) {
      return this.taskCapabilitiesFromServerTasks(projectCapabilities?.tasks);
    },

    defaultAiProfileSelection() {
      return { primary_profile_id: '', primary_model: '', primary_reasoning_type: '', fallback_profile_ids: [] };
    },

    defaultTaskAiProfileSelections() {
      const out = {};
      for (const task of this.aiProfileTaskTypes()) {
        out[task.key] = this.defaultAiProfileSelection();
      }
      return out;
    },

    defaultTaskTimeouts() {
      return this.cloneData(defaultTaskTimeouts());
    },

    normalizeTaskTimeouts(value) {
      const source = value || {};
      return {
        bootstrap: {
          timeout: Number(source.bootstrap?.timeout) || 0,
          conclude_timeout: Number(source.bootstrap?.conclude_timeout) || 0,
        },
        explore: {
          timeout: Number(source.explore?.timeout) || 0,
          conclude_timeout: Number(source.explore?.conclude_timeout) || 0,
        },
        reason: {
          timeout: Number(source.reason?.timeout) || 0,
        },
      };
    },

    taskTimeoutsComplete(value) {
      const t = this.normalizeTaskTimeouts(value);
      return t.bootstrap.timeout > 0
        && t.bootstrap.conclude_timeout > 0
        && t.explore.timeout > 0
        && t.explore.conclude_timeout > 0
        && t.reason.timeout > 0;
    },

    taskTimeoutsForPayload(value) {
      const t = this.normalizeTaskTimeouts(value);
      if (!this.taskTimeoutsComplete(t)) {
        throw new Error('Set all task timeouts to positive seconds before creating the project.');
      }
      return t;
    },

    taskTimeoutsFromExecutionConfigs(configs) {
      for (const task of ['bootstrap', 'explore', 'reason']) {
        const taskTimeouts = configs?.[task]?.task_timeouts;
        if (taskTimeouts) return this.normalizeTaskTimeouts(taskTimeouts);
      }
      throw new Error('Source project execution config is missing task_timeouts.');
    },

    ensureTaskAiProfileSelections(target) {
      if (!target.ai_profiles) {
        target.ai_profiles = this.defaultTaskAiProfileSelections();
      }
      for (const task of this.task_types) {
        if (!target.ai_profiles[task]) target.ai_profiles[task] = this.defaultAiProfileSelection();
        if (!Array.isArray(target.ai_profiles[task].fallback_profile_ids)) target.ai_profiles[task].fallback_profile_ids = [];
        if (target.ai_profiles[task].primary_model == null) target.ai_profiles[task].primary_model = '';
        if (target.ai_profiles[task].primary_reasoning_type == null) target.ai_profiles[task].primary_reasoning_type = '';
      }
      return target.ai_profiles;
    },

    aiProfileSelectionHasValue(selection) {
      return !!(selection && (selection.primary_profile_id || selection.primary_model || selection.primary_reasoning_type || (selection.fallback_profile_ids || []).length > 0));
    },

    taskAiProfileSelectionsHasValue(selections) {
      return Object.values(selections || {}).some(selection => this.aiProfileSelectionHasValue(selection));
    },

    removeProfileFromTaskAiSelections(selections, profileId) {
      for (const selection of Object.values(selections || {})) {
        if (!selection) continue;
        if (selection.primary_profile_id === profileId) {
          selection.primary_profile_id = '';
          selection.primary_model = '';
          selection.primary_reasoning_type = '';
        }
        selection.fallback_profile_ids = (selection.fallback_profile_ids || []).filter(id => id !== profileId);
      }
    },

    compactTaskAiProfileSelections(selections) {
      const current = selections || {};
      return {
        bootstrap: {
          primary_profile_id: current.bootstrap?.primary_profile_id || null,
          primary_model: current.bootstrap?.primary_model || null,
          primary_reasoning_type: current.bootstrap?.primary_reasoning_type || null,
          fallback_profile_ids: current.bootstrap?.fallback_profile_ids || [],
        },
        explore: {
          primary_profile_id: current.explore?.primary_profile_id || null,
          primary_model: current.explore?.primary_model || null,
          primary_reasoning_type: current.explore?.primary_reasoning_type || null,
          fallback_profile_ids: current.explore?.fallback_profile_ids || [],
        },
        reason: {
          primary_profile_id: current.reason?.primary_profile_id || null,
          primary_model: current.reason?.primary_model || null,
          primary_reasoning_type: current.reason?.primary_reasoning_type || null,
          fallback_profile_ids: current.reason?.fallback_profile_ids || [],
        },
      };
    },

    taskAiProfileSelectionsComplete(target, items = null) {
      const availableItems = (items || this.aiProfiles || []).filter(item => item.available !== false);
      const availableIds = new Set(availableItems.map(item => item.id));
      if (availableIds.size === 0) return false;
      const selections = this.ensureTaskAiProfileSelections(target);
      return this.aiProfileTaskTypes().every(task => {
        const selection = selections[task.key] || {};
        const id = selection.primary_profile_id || '';
        const profile = availableItems.find(item => item.id === id);
        const modelOptions = this.aiProfileModelOptions(profile);
        return id
          && availableIds.has(id)
          && selection.primary_model
          && modelOptions.includes(selection.primary_model)
          && selection.primary_reasoning_type;
      });
    },

    ensureAllTaskAiProfilesSelected(target, items) {
      const availableItems = (items || []).filter(item => item.available !== false);
      if (availableItems.length === 0) return false;
      const selections = this.ensureTaskAiProfileSelections(target);
      for (const task of this.aiProfileTaskTypes()) {
        const selection = selections[task.key];
        if (!selection.primary_profile_id || !availableItems.some(item => item.id === selection.primary_profile_id)) {
          selection.primary_profile_id = availableItems[0].id;
          selection.fallback_profile_ids = [];
        }
        this.hydrateTaskAiSelectionFromProfile(selection, availableItems.find(item => item.id === selection.primary_profile_id));
      }
      return true;
    },

    hydrateTaskAiSelectionFromProfile(selection, profile) {
      if (!profile) {
        selection.primary_profile_id = '';
        selection.primary_model = '';
        selection.primary_reasoning_type = '';
        selection.fallback_profile_ids = [];
        return;
      }
      const modelOptions = this.aiProfileModelOptions(profile);
      if (!selection.primary_model || !modelOptions.includes(selection.primary_model)) {
        selection.primary_model = profile.model || modelOptions[0] || '';
      }
      if (!selection.primary_reasoning_type) {
        selection.primary_reasoning_type = profile.model_reasoning_effort || '';
      }
    },

    taskAiModelOptions(target, taskType, items) {
      const selection = this.ensureTaskAiProfileSelections(target)[taskType] || {};
      const profile = (items || []).find(item => item.id === selection.primary_profile_id);
      return this.aiProfileModelOptions(profile);
    },

    setTaskAiModel(target, taskType, model) {
      this.ensureTaskAiProfileSelections(target)[taskType].primary_model = model || '';
    },

    setTaskAiReasoning(target, taskType, reasoning) {
      this.ensureTaskAiProfileSelections(target)[taskType].primary_reasoning_type = reasoning || '';
    },

    selectNewProjectAiProfile(profileId, taskType = 'explore') {
      const profile = this.newProjectAiProfileItems().find(item => item.id === profileId);
      const selection = this.ensureTaskAiProfileSelections(this.newProject)[taskType];
      selection.primary_profile_id = profile?.id || '';
      selection.fallback_profile_ids = [];
      this.hydrateTaskAiSelectionFromProfile(selection, profile);
    },

    clearNewProjectAiProfiles() {
      this.newProject.ai_profiles = this.defaultTaskAiProfileSelections();
      this.ensureAllTaskAiProfilesSelected(this.newProject, this.newProjectAiProfileItems());
    },

    replayConfigAiProfileItems() {
      return (this.aiProfiles || []).filter(item => item.available !== false);
    },

    selectReplayConfigAiProfile(profileId, taskType = 'explore') {
      const selection = this.ensureTaskAiProfileSelections(this.replayConfig)[taskType];
      const profile = this.replayConfigAiProfileItems().find(item => item.id === profileId);
      selection.primary_profile_id = profile?.id || '';
      selection.fallback_profile_ids = [];
      this.hydrateTaskAiSelectionFromProfile(selection, profile);
    },

    clearReplayConfigAiProfiles() {
      this.replayConfig.ai_profiles = this.defaultTaskAiProfileSelections();
      this.ensureAllTaskAiProfilesSelected(this.replayConfig, this.replayConfigAiProfileItems());
    },

    capabilitiesUnavailableText() {
      const mcp = this.capabilities.unavailable?.mcp_server_ids || [];
      const skills = this.capabilities.unavailable?.skill_ids || [];
      const parts = [];
      if (mcp.length) parts.push(`Unavailable MCP: ${mcp.join(', ')}`);
      if (skills.length) parts.push(`Unavailable skills: ${skills.join(', ')}`);
      return parts.join(' · ');
    },
  };
}
