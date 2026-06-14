window.CairnParts = window.CairnParts || {};
CairnParts.capabilities = function () {
  return {
    capabilities: {
      catalog: [],
      tasks: defaultTaskCapabilitiesMap(),
      health: {},
      unavailable: { mcp_server_ids: [], skill_ids: [] },
      projectAiProfiles: { catalog: [], selections: defaultTaskAiProfileSelections(), snapshots: [], unavailable_profile_ids: [] },
    },
    capabilityAdmin: { catalog: [], health: {} },
    capabilityForm: defaultCapabilityForm(),
    capabilityFormOpen: false,
    capabilityEditId: '',
    capabilitiesSaving: false,
    newProjectCapabilityPanel: 'bootstrap',
    showSettings: false,
    replayConfigCapabilityPanel: 'bootstrap',
    settingsForm: { intent_timeout: 5, reason_timeout: 5 },
    capabilityAdminPanel: 'bootstrap',
    proxyForm: { id: '', name: '', type: 'socks5', host: '', port: 1080, username: '', password: '' },
    proxyFormOpen: false,
    aiProfiles: [],
    aiProfileCheckBusy: {},
    aiProfileForm: {
      id: '',
      name: '',
      description: '',
      worker_type: 'codex',
      provider: '',
      base_url: '',
      model: '',
      models_text: '',
      available: true,
      healthcheck_timeout: 1.0,
      model_reasoning_effort: '',
      // Write-only sk. skTouched tracks whether the user has typed
      // anything since the form was opened: untouched means "send
      // null and keep whatever the server has". skStoredPreview shows
      // the masked server-side value next to the input on edit.
      sk: '',
      skTouched: false,
      skStoredPreview: '',
    },
    aiProfileFormOpen: false,
    isSyncingAiProfiles: false,

    settingsSection: 'server',

    settingsSectionTitle() {
      const item = this.adminNavItems().find(entry => entry.section === this.settingsSection);
      return item ? item.label : 'Settings';
    },

    async loadSettings() {
      try {
        const s = await this.api('GET', '/settings');
        this.settingsForm.intent_timeout = s.intent_timeout;
        this.settingsForm.reason_timeout = s.reason_timeout;
      } catch(e) { console.error(e); }
      this.capabilityAdminPanel = 'bootstrap';
      await this.loadCapabilityAdmin();
    },

    async openSettings() {
      await this.navigateSettings('server');
    },

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

    resetProxyForm() {
      this.proxyForm = { id: '', name: '', type: 'socks5', host: '', port: 1080, username: '', password: '' };
      this.proxyFormOpen = false;
    },

    openCreateProxy() {
      this.resetProxyForm();
      this.proxyFormOpen = true;
    },

    async openEditProxy(proxyId) {
      try {
        const p = await this.api('GET', `/proxies/${encodeURIComponent(proxyId)}`);
        this.proxyForm = {
          id: p.id,
          name: p.name || '',
          type: p.type || 'socks5',
          host: p.host || '',
          port: p.port || 1080,
          username: p.username || '',
          password: p.password || '',
        };
        this.proxyFormOpen = true;
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    cancelProxyEdit() {
      this.resetProxyForm();
    },

    async saveProxy() {
      const body = {
        name: this.proxyForm.name.trim(),
        type: this.proxyForm.type,
        host: this.proxyForm.host.trim(),
        port: Number(this.proxyForm.port),
        username: this.proxyForm.username || null,
        password: this.proxyForm.password || null,
      };
      try {
        if (this.proxyForm.id) {
          await this.api('PUT', `/proxies/${encodeURIComponent(this.proxyForm.id)}`, body);
          this.showToast('Proxy saved');
        } else {
          await this.api('POST', '/proxies', body);
          this.showToast('Proxy created');
        }
        this.resetProxyForm();
        await this.loadProxies();
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async deleteProxy(proxyId, proxyName) {
      const ok = window.confirm(`Delete proxy "${proxyName}"? Projects that reference it will fall back to direct connection.`);
      if (!ok) return;
      try {
        await this.api('DELETE', `/proxies/${encodeURIComponent(proxyId)}`);
        this.showToast('Proxy deleted');
        if (this.proxyForm.id === proxyId) this.resetProxyForm();
        await this.loadProxies();
        if (this.newProject && this.newProject.proxy_id === proxyId) this.newProject.proxy_id = '';
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async loadAiProfiles() {
      try {
        this.aiProfiles = await this.api('GET', '/ai-profiles') || [];
      } catch (e) {
        console.error(e);
        this.aiProfiles = [];
      }
    },

    resetAiProfileForm() {
      this.aiProfileForm = {
        id: '',
        name: '',
        description: '',
        worker_type: 'codex',
        provider: '',
        base_url: '',
        model: '',
        models_text: '',
        available: true,
        detail: '',
        healthcheck_timeout: 1.0,
        model_reasoning_effort: '',
        sk: '',
        skTouched: false,
        skStoredPreview: '',
      };
      this.aiProfileFormOpen = false;
    },

    setAiProfileWorkerType(type) {
      if (this.aiProfileForm.id) return; // type is locked on edit
      if (this.aiProfileForm.worker_type === type) return;
      this.aiProfileForm.worker_type = type;
    },

    aiProfileCanonicalEnv(workerType) {
      return workerType === 'claudecode' ? 'ANTHROPIC_AUTH_TOKEN' : 'OPENAI_API_KEY';
    },

    aiProfileBaseUrlPlaceholder() {
      return this.aiProfileForm.worker_type === 'codex'
        ? 'base URL (e.g. https://api.openai.com/v1)'
        : 'base URL (e.g. https://api.anthropic.com)';
    },

    aiProfileModelPlaceholder() {
      return this.aiProfileForm.worker_type === 'codex'
        ? 'model id (e.g. gpt-5.4)'
        : 'model id (e.g. claude-sonnet-4.5)';
    },

    aiProfileSkPlaceholder() {
      return this.aiProfileForm.worker_type === 'codex'
        ? 'sk-... (Codex, write only; leave blank to keep current)'
        : 'sk-ant-... (Claude, write only; leave blank to keep current)';
    },

    clearStoredAiProfileSk() {
      // User clicked "clear stored key" on an existing profile. Mark
      // the form as touched with an empty value, so saveAiProfile
      // sends "" to the PUT endpoint, which the server interprets
      // as "clear the stored sk".
      this.aiProfileForm.skTouched = true;
      this.aiProfileForm.sk = '';
    },

    openCreateAiProfile() {
      this.resetAiProfileForm();
      this.aiProfileFormOpen = true;
    },

    async openEditAiProfile(profileId) {
      try {
        const p = await this.api('GET', `/ai-profiles/${encodeURIComponent(profileId)}`);
        this.aiProfileForm = {
          id: p.id,
          name: p.name || '',
          description: p.description || '',
          worker_type: p.worker_type || 'codex',
          provider: p.provider || '',
          base_url: p.base_url || '',
          model: p.model || '',
          models_text: this.aiProfileModelOptions(p).join('\n'),
          available: p.available !== false,
          detail: p.detail || '',
          healthcheck_timeout: Number(p.healthcheck_timeout) || 1.0,
          model_reasoning_effort: p.model_reasoning_effort || '',
          // Write-only: the server never echoes the raw sk value, only
          // sk_set / sk_preview. Keep the input blank; show the
          // preview next to it.
          sk: '',
          skTouched: false,
          skStoredPreview: p.sk_preview || '',
        };
        this.aiProfileFormOpen = true;
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    cancelAiProfileEdit() {
      this.resetAiProfileForm();
    },

    async saveAiProfile() {
      const base = {
        name: this.aiProfileForm.name.trim(),
        description: this.aiProfileForm.description || '',
        worker_type: this.aiProfileForm.worker_type,
        provider: this.aiProfileForm.provider || '',
        base_url: this.aiProfileForm.base_url || '',
        model: this.aiProfileForm.model.trim(),
        models: this.aiProfileModelsFromForm(),
        available: this.aiProfileForm.available,
        detail: this.aiProfileForm.detail || '',
        healthcheck_timeout: Number(this.aiProfileForm.healthcheck_timeout) || 1.0,
        model_reasoning_effort: this.aiProfileForm.model_reasoning_effort || null,
      };
      // sk semantics:
      //   POST  -> always include the literal sk ("" means "do not store")
      //   PUT   -> include only if skTouched. Non-empty replaces, ""
      //           clears, untouched (omitted) leaves the server value
      //           intact.
      let body;
      if (this.aiProfileForm.id) {
        body = { ...base };
        if (this.aiProfileForm.skTouched) {
          body.sk = this.aiProfileForm.sk;
        }
      } else {
        body = { ...base, sk: this.aiProfileForm.sk };
      }
      try {
        if (this.aiProfileForm.id) {
          await this.api('PUT', `/ai-profiles/${encodeURIComponent(this.aiProfileForm.id)}`, body);
          this.showToast('AI profile saved');
        } else {
          await this.api('POST', '/ai-profiles', body);
          this.showToast('AI profile created');
        }
        this.resetAiProfileForm();
        await this.loadAiProfiles();
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    aiProfileModelsFromForm() {
      const values = [
        this.aiProfileForm.model || '',
        ...String(this.aiProfileForm.models_text || '').split(/[\n,]/),
      ].map(item => item.trim()).filter(Boolean);
      return [...new Set(values)];
    },

    async deleteAiProfile(profileId, profileName) {
      const ok = window.confirm(`Delete AI profile "${profileName}"? Existing project snapshots are preserved, but the profile can no longer be selected for new projects.`);
      if (!ok) return;
      try {
        await this.api('DELETE', `/ai-profiles/${encodeURIComponent(profileId)}`);
        this.showToast('AI profile deleted');
        if (this.aiProfileForm.id === profileId) this.resetAiProfileForm();
        await this.loadAiProfiles();
        if (this.newProject) this.removeProfileFromTaskAiSelections(this.newProject.ai_profiles, profileId);
        if (this.replayConfig) this.removeProfileFromTaskAiSelections(this.replayConfig.ai_profiles, profileId);
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async refreshAiProfiles() {
      await this.loadAiProfiles();
    },

    async checkAiProfile(profileId, profileName) {
      if (!profileId || this.aiProfileCheckBusy[profileId]) return;
      this.aiProfileCheckBusy = { ...this.aiProfileCheckBusy, [profileId]: true };
      try {
        const result = await this.api('POST', `/ai-profiles/${encodeURIComponent(profileId)}/check`, {});
        if (!result || !result.request_id) {
          throw new Error('failed to queue AI profile check');
        }
        this.showToast(`AI profile check queued: ${profileName}`);
        await this.waitForAiProfileCheck(profileId);
      } catch (e) {
        this.showToast(e.message, 'error');
      } finally {
        this.aiProfileCheckBusy = { ...this.aiProfileCheckBusy, [profileId]: false };
      }
    },

    async waitForAiProfileCheck(profileId) {
      const previous = (this.aiProfiles || []).find(item => item.id === profileId);
      const previousAt = previous ? (previous.last_health_at || '') : '';
      const started = Date.now();
      while (Date.now() - started < 20000) {
        await new Promise(resolve => window.setTimeout(resolve, 1000));
        await this.loadAiProfiles();
        const profile = (this.aiProfiles || []).find(item => item.id === profileId);
        if (!profile) throw new Error(`AI profile not found: ${profileId}`);
        if ((profile.last_health_at || '') !== previousAt && profile.last_health_at) {
          if (profile.last_health_ok === false) {
            this.showToast(`AI profile check failed: ${profile.last_health_message || 'health check failed'}`, 'error');
          } else {
            this.showToast('AI profile check passed');
          }
          return;
        }
      }
      throw new Error('AI profile check timed out waiting for dispatcher result');
    },

    // AI Profiles are edited directly in dispatch.yaml. The Check button
    // enqueues a dispatcher health probe; there is no dispatcher startup
    // sync or database mirror for profile definitions.

    aiProfileHealthDotClass(p) {
      if (!p.available) return 'bg-rose-500';
      if ((p.warnings || []).length > 0) return 'bg-amber-400';
      if (p.last_health_at && p.last_health_ok === false) return 'bg-rose-500';
      if (p.last_health_at && p.last_health_ok === true) return 'bg-emerald-500';
      return 'bg-slate-300';
    },

    aiProfileHealthTitle(p) {
      if (!p.available) return `Unavailable: ${p.last_health_message || 'health check failed'}`;
      if (p.last_health_ok === false) return `Last health check failed: ${p.last_health_message || ''}`;
      if (p.last_health_at) return `Last health check @ ${p.last_health_at}: ok`;
      return 'No health check yet';
    },

    async loadCapabilities() {
      if (!this.selectedProjectId) return;
      try {
        const [data, aiData] = await Promise.all([
          this.api('GET', `/projects/${this.selectedProjectId}/capabilities`),
          this.api('GET', `/projects/${this.selectedProjectId}/ai-profiles`).catch(() => null),
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
      };
    },

    openCreateCapability() {
      this.capabilityEditId = '';
      this.capabilityForm = this.defaultCapabilityForm();
      this.capabilityFormOpen = true;
    },

    cancelCapabilityEdit() {
      this.capabilityEditId = '';
      this.capabilityForm = this.defaultCapabilityForm();
      this.capabilityFormOpen = false;
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
        activation_hint: item.activation_hint || '',
        preferred_mcp_ids: Array.isArray(item.preferred_mcp_ids) ? [...item.preferred_mcp_ids] : [],
        transport: item.transport,
        command: item.command || '',
        args: Array.isArray(item.args) ? item.args.join(' ') : (item.args || ''),
        url: item.url || '',
        source_path: item.source_path || '',
        headers: (item.headers && typeof item.headers === 'object') ? item.headers : {},
        authorization_header: item.headers && typeof item.headers === 'object' ? (item.headers.Authorization || '') : '',
        probe_config: (item.probe_config && typeof item.probe_config === 'object') ? item.probe_config : {},
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
      const normalizeStringList = (value) => {
        if (Array.isArray(value)) {
          return value.map(s => String(s || '').trim()).filter(Boolean);
        }
        if (typeof value === 'string') {
          return value.split(/[\s,]+/).map(s => s.trim()).filter(Boolean);
        }
        return [];
      };
      const basePayload = {
        kind: this.capabilityForm.kind,
        id: this.capabilityForm.id.trim(),
        name: this.capabilityForm.name.trim(),
        description: this.capabilityForm.description || '',
        task_types: normalizeStringList(this.capabilityForm.task_types),
        requires_ids: normalizeStringList(this.capabilityForm.requires_ids),
        required_skill_ids: normalizeStringList(this.capabilityForm.required_skill_ids),
        use_when: normalizeStringList(this.capabilityForm.use_when),
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
        payload.headers = (this.capabilityForm.headers && typeof this.capabilityForm.headers === 'object')
          ? this.capabilityForm.headers : {};
        if (this.capabilityForm.authorization_header) {
          payload.headers.Authorization = this.capabilityForm.authorization_header;
        } else {
          delete payload.headers.Authorization;
        }
        payload.probe_config = (this.capabilityForm.probe_config && typeof this.capabilityForm.probe_config === 'object')
          ? this.capabilityForm.probe_config : {};
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
      try {
        const entry = await this.api('POST', `/capabilities/admin/${kind}/${encodeURIComponent(id)}/probe`, {});
        this.showToast(`Probe ${entry.status}: ${entry.message || 'ok'}`);
        await this.loadCapabilityAdmin();
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async loadCapabilityAdmin() {
      try {
        const data = await this.api('GET', '/capabilities/admin');
        this.capabilityAdmin = { catalog: data.catalog || [], health: data.health || {} };
      } catch (e) {
        this.capabilityAdmin = { catalog: [], health: {} };
      }
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
      const out = {};
      for (const task of this.capabilityTaskTypes()) {
        const entry = capabilities?.[task.key] || this.defaultTaskCapabilities();
        out[task.key] = {
          mcp_server_ids: [...(entry.user_mcp_server_ids || entry.mcp_server_ids || [])],
          skill_ids: this.sanitizeUserSkillIdsForProjectPayload(entry.user_skill_ids || []),
        };
      }
      return out;
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

    async saveServerSettings() {
      try {
        await this.api('PUT', '/settings', this.settingsForm);
        this.showSettings = false;
        this.showToast('Server settings saved');
      } catch(e) { this.showToast(e.message, 'error'); }
    },
  };
};
