export function createSettingsAdminState() {
  return {
    settingsForm: { intent_timeout: 5, reason_timeout: 5 },
    runtimeLimitsForm: { max_workers: 8, max_running_projects: 3, max_project_workers: 2, interval: 3, healthcheck_timeout: 20 },
    taskTimeoutsForm: {
      bootstrap_timeout: 300, bootstrap_conclude_timeout: 120,
      explore_timeout: 900, explore_conclude_timeout: 180,
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

    applySystemSettings(data) {
      if (!data) return;
      Object.assign(this.settingsForm, data.settings || {});
      Object.assign(this.runtimeLimitsForm, data.runtime_limits || {});
      const t = data.task_timeouts || {};
      if (t.bootstrap) {
        this.taskTimeoutsForm.bootstrap_timeout = t.bootstrap.timeout;
        this.taskTimeoutsForm.bootstrap_conclude_timeout = t.bootstrap.conclude_timeout;
      }
      if (t.explore) {
        this.taskTimeoutsForm.explore_timeout = t.explore.timeout;
        this.taskTimeoutsForm.explore_conclude_timeout = t.explore.conclude_timeout;
      }
      if (t.reason) {
        this.taskTimeoutsForm.reason_timeout = t.reason.timeout;
        this.taskTimeoutsForm.reason_max_intents = t.reason.max_intents;
      }
      const o = data.observability || {};
      Object.assign(this.observabilityForm, o);
      this.observabilityForm.redaction_patterns_text = (o.redaction_patterns || []).join('\n');
      Object.assign(this.serverLogRetentionForm, data.server_log_retention || {});
    },

    systemSettingsPayload() {
      const observability = {
        ...this.observabilityForm,
        redaction_patterns: (this.observabilityForm.redaction_patterns_text || '').split('\n').map(s => s.trim()).filter(Boolean),
      };
      delete observability.redaction_patterns_text;
      return {
        settings: this.settingsForm,
        runtime_limits: this.runtimeLimitsForm,
        task_timeouts: {
          bootstrap: { timeout: this.taskTimeoutsForm.bootstrap_timeout, conclude_timeout: this.taskTimeoutsForm.bootstrap_conclude_timeout },
          explore: { timeout: this.taskTimeoutsForm.explore_timeout, conclude_timeout: this.taskTimeoutsForm.explore_conclude_timeout },
          reason: { timeout: this.taskTimeoutsForm.reason_timeout, max_intents: this.taskTimeoutsForm.reason_max_intents },
        },
        observability,
        server_log_retention: this.serverLogRetentionForm,
      };
    },

    async loadSystemSettings() {
      try {
        const data = await this.api('GET', '/system-settings');
        this.applySystemSettings(data);
      } catch(e) { console.error(e); }
    },

    async saveSystemSettings() {
      try {
        const data = await this.api('PUT', '/system-settings', this.systemSettingsPayload());
        this.applySystemSettings(data);
        this.showToast('System settings saved');
      } catch(e) { this.showToast(e.message, 'error'); }
    },
  };
}
