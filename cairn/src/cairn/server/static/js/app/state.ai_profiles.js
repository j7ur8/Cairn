export function createAiProfilesState() {
  return {
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
      sk: '',
      skTouched: false,
      skStoredPreview: '',
    },
    aiProfileFormOpen: false,
    isSyncingAiProfiles: false,

    async loadAiProfiles() {
      try {
        this.aiProfiles = await this.api('GET', '/ai-profiles') || [];
      } catch (e) {
        console.error(e);
        this.aiProfiles = [];
      }
    },

    async loadProjectAiProfiles(projectId = this.selectedProjectId) {
      if (!projectId) return null;
      return await this.api('GET', `/projects/${projectId}/ai-profiles`);
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
      if (this.aiProfileForm.id) return;
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
  };
}