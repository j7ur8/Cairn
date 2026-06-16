window.CairnParts = window.CairnParts || {};
CairnParts.settings = function () {
  return {
    showSettings: false,
    settingsSection: 'server',
    settingsForm: { intent_timeout: 5, reason_timeout: 5 },

    adminNavItems() {
      return [
        { section: 'server', label: 'Server Settings', icon: 'SV' },
        { section: 'runtime', label: 'Runtime & Limits', icon: 'RT' },
        { section: 'prompts', label: 'Prompts', icon: 'PR' },
        { section: 'tasks', label: 'Task Timeouts', icon: 'TS' },
        { section: 'observability', label: 'Observability', icon: 'OB' },
        { section: 'system', label: 'Log & Retention', icon: 'SY' },
        { section: 'ai', label: 'AI Profiles', icon: 'AI' },
        { section: 'capabilities', label: 'Capabilities', icon: 'CA' },
        { section: 'proxies', label: 'Proxies', icon: 'PX' },
      ];
    },

    settingsSectionTitle() {
      const item = this.adminNavItems().find(entry => entry.section === this.settingsSection);
      return item ? item.label : 'Settings';
    },

    async openSettings() {
      await this.navigateSettings('server');
    },

    async navigateSettings(section = 'server') {
      this.settingsSection = section;
      this.showSettings = false;
      this.view = 'settings';
      this.mobileNavOpen = false;
      await this.loadSettingsSection(section);
    },

    async loadSettingsSection(section = this.settingsSection) {
      const loaders = {
        server: () => this.loadSettings(),
        runtime: () => this.loadRuntimeLimits(),
        prompts: async () => {
          if (!this.runtimeLimitsForm?.prompt_group) await this.loadRuntimeLimits();
          this.promptGroupSelected = this.runtimeLimitsForm.prompt_group || this.promptGroupSelected;
          await this.loadPromptGroups();
        },
        tasks: () => this.loadTaskTimeouts(),
        observability: () => this.loadObservability(),
        system: () => this.loadServerLogRetention(),
        ai: () => this.loadAiProfiles(),
        capabilities: () => this.loadCapabilityAdmin(),
        proxies: () => this.loadProxies(),
      };
      const loader = loaders[section] || loaders.server;
      await loader();
    },

    async loadSettings() {
      try {
        const s = await this.api('GET', '/settings');
        this.settingsForm.intent_timeout = s.intent_timeout;
        this.settingsForm.reason_timeout = s.reason_timeout;
      } catch(e) { console.error(e); }
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
