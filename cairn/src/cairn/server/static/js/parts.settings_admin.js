window.CairnParts = window.CairnParts || {};
CairnParts.settings_admin = function () {
  return {
    runtimeLimitsForm: { max_workers: 8, max_running_projects: 3, max_project_workers: 4, interval: 3, healthcheck_timeout: 20, prompt_group: 'default' },
    taskTimeoutsForm: {
      bootstrap_timeout: 300, bootstrap_conclude_timeout: 90,
      explore_timeout: 300, explore_conclude_timeout: 90,
      reason_timeout: 300, reason_max_intents: 2,
    },
    observabilityForm: {
      enabled: true,
      record_prompts: true, record_stdout: true, record_stderr: true,
      record_raw_worker_stream: false,
      max_event_bytes: 16384, max_bytes_per_execution: 10485760,
      flush_interval_ms: 250, flush_max_bytes: 8192,
      retention_days: 14, redaction_patterns_text: '',
    },
    serverLogRetentionForm: {
      log_level: 'INFO', log_format: 'text',
      retention_enabled: true, retention_interval_seconds: 21600,
    },

    async loadRuntimeLimits() {
      try {
        const r = await this.api('GET', '/runtime-limits');
        Object.assign(this.runtimeLimitsForm, r);
        if (!this.promptGroupSelected) this.promptGroupSelected = r.prompt_group || 'default';
      } catch(e) { console.error(e); }
    },

    async loadTaskTimeouts() {
      try {
        const t = await this.api('GET', '/task-timeouts');
        this.taskTimeoutsForm.bootstrap_timeout = t.bootstrap.timeout;
        this.taskTimeoutsForm.bootstrap_conclude_timeout = t.bootstrap.conclude_timeout;
        this.taskTimeoutsForm.explore_timeout = t.explore.timeout;
        this.taskTimeoutsForm.explore_conclude_timeout = t.explore.conclude_timeout;
        this.taskTimeoutsForm.reason_timeout = t.reason.timeout;
        this.taskTimeoutsForm.reason_max_intents = t.reason.max_intents;
      } catch(e) { console.error(e); }
    },

    async loadObservability() {
      try {
        const o = await this.api('GET', '/observability');
        Object.assign(this.observabilityForm, o);
        this.observabilityForm.redaction_patterns_text = (o.redaction_patterns || []).join('\n');
      } catch(e) { console.error(e); }
    },

    async loadServerLogRetention() {
      try {
        const s = await this.api('GET', '/server-log-retention');
        Object.assign(this.serverLogRetentionForm, s);
      } catch(e) { console.error(e); }
    },

    async saveRuntimeLimits() {
      try {
        await this.api('PUT', '/runtime-limits', this.runtimeLimitsForm);
        this.showToast('Runtime limits saved');
      } catch(e) { this.showToast(e.message, 'error'); }
    },

    async saveTaskTimeouts() {
      try {
        const payload = {
          bootstrap: { timeout: this.taskTimeoutsForm.bootstrap_timeout, conclude_timeout: this.taskTimeoutsForm.bootstrap_conclude_timeout },
          explore: { timeout: this.taskTimeoutsForm.explore_timeout, conclude_timeout: this.taskTimeoutsForm.explore_conclude_timeout },
          reason: { timeout: this.taskTimeoutsForm.reason_timeout, max_intents: this.taskTimeoutsForm.reason_max_intents },
        };
        await this.api('PUT', '/task-timeouts', payload);
        this.showToast('Task timeouts saved');
      } catch(e) { this.showToast(e.message, 'error'); }
    },

    async saveObservability() {
      try {
        const payload = {
          ...this.observabilityForm,
          redaction_patterns: (this.observabilityForm.redaction_patterns_text || '').split('\n').map(s => s.trim()).filter(Boolean),
        };
        delete payload.redaction_patterns_text;
        await this.api('PUT', '/observability', payload);
        this.showToast('Observability settings saved');
      } catch(e) { this.showToast(e.message, 'error'); }
    },

    async saveServerLogRetention() {
      try {
        await this.api('PUT', '/server-log-retention', this.serverLogRetentionForm);
        this.showToast('Log & retention settings saved');
      } catch(e) { this.showToast(e.message, 'error'); }
    },
  };
};
