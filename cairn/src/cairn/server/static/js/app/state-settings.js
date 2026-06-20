export function createSettingsState() {
  return {
    showSettings: false,
    settingsSection: 'system',

    adminNavItems() {
      return [
        { section: 'system', label: 'System', icon: 'SY' },
        { section: 'prompts', label: 'Prompts', icon: 'PR' },
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
      await this.navigateSettings('system');
    },

    async navigateSettings(section = 'system') {
      this.settingsSection = section;
      this.showSettings = false;
      this.view = 'settings';
      this.mobileNavOpen = false;
      await this.loadSettingsSection(section);
    },

    async loadSettingsSection(section = this.settingsSection) {
      const loaders = {
        system: () => this.loadSystemSettings(),
        prompts: () => this.loadPrompts(),
        ai: () => this.loadAiProfiles(),
        capabilities: () => this.loadCapabilityAdmin(),
        proxies: () => this.loadProxies(),
      };
      const loader = loaders[section] || loaders.system;
      await loader();
    },

    async loadSettings() {
      return this.loadSystemSettings();
    },

    async saveServerSettings() {
      return this.saveSystemSettings();
    },
  };
}
