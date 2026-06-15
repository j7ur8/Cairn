window.CairnParts = window.CairnParts || {};
CairnParts.ui = function () {
  return {
    sideTab: 'detail',
    sidePanelWidth: 320,
    isResizingPanel: false,
    showLocalPrefs: false,
    localPrefs: { actor_name: 'Human', layout_mode: 'dagre_tb' },
    toast: { show: false, message: '', type: 'info' },
    // --- Auth state ---
    _panelResizeFrame: null,
    _panelResizePendingEvent: null,
    navCollapsed: false,
    mobileNavOpen: false,
    showToast(msg, type = 'info') {
      this.toast = { show: true, message: msg, type };
      setTimeout(() => this.toast.show = false, 3000);
    },

    loadLocalPrefs() {
      try {
        const raw = localStorage.getItem('cairn.localPrefs');
        if (!raw) {
          this.localPrefs.actor_name = 'Human';
        } else {
          const parsed = JSON.parse(raw);
          if (typeof parsed.actor_name === 'string') this.localPrefs.actor_name = parsed.actor_name;
          if (this.isValidLayoutMode(parsed.layout_mode)) {
            this.localPrefs.layout_mode = parsed.layout_mode;
          } else if (parsed.layout_dir === 'TB' || parsed.layout_dir === 'LR') {
            this.localPrefs.layout_mode = parsed.layout_dir === 'LR' ? 'dagre_lr' : 'dagre_tb';
          }
        }
        const rawPanelWidth = localStorage.getItem('cairn.sidePanelWidth');
        if (rawPanelWidth !== null) {
          const savedPanelWidth = Number(rawPanelWidth);
          if (Number.isFinite(savedPanelWidth)) this.sidePanelWidth = savedPanelWidth;
        }
        const rawLlmPanelWidth = localStorage.getItem('cairn.llmPanelWidth');
        if (rawLlmPanelWidth !== null) {
          const savedLlmPanelWidth = Number(rawLlmPanelWidth);
          if (Number.isFinite(savedLlmPanelWidth)) this.llmPanelWidth = savedLlmPanelWidth;
        }
        this.llmPanelCollapsed = localStorage.getItem('cairn.llmPanelCollapsed') === 'true';
        this.navCollapsed = localStorage.getItem('cairn.navCollapsed') === '1';
      } catch (e) {
        console.error(e);
      }
      if (!this.localPrefs.actor_name.trim()) this.localPrefs.actor_name = 'Human';
      if (!this.isValidLayoutMode(this.localPrefs.layout_mode)) this.localPrefs.layout_mode = 'dagre_tb';
      this.layoutMode = this.localPrefs.layout_mode;
    },

    saveLocalPrefs() {
      try {
        localStorage.setItem('cairn.localPrefs', JSON.stringify(this.localPrefs));
      } catch (e) {
        console.error(e);
      }
    },

    saveNavPrefs() {
      try {
        localStorage.setItem('cairn.navCollapsed', this.navCollapsed ? '1' : '0');
      } catch (e) {
        console.error(e);
      }
    },

    appShellVisible() {
      return this.appBootstrapped && !this.showLogin;
    },

    adminNavItems() {
      return [
        { section: 'server', label: 'Server Settings', icon: 'SV' },
        { section: 'runtime', label: 'Runtime & Limits', icon: 'RT' },
        { section: 'tasks', label: 'Task Timeouts', icon: 'TS' },
        { section: 'observability', label: 'Observability', icon: 'OB' },
        { section: 'system', label: 'Log & Retention', icon: 'SY' },
        { section: 'ai', label: 'AI Profiles', icon: 'AI' },
        { section: 'capabilities', label: 'Capabilities', icon: 'CA' },
        { section: 'proxies', label: 'Proxies', icon: 'PX' },
      ];
    },

    async navigateSettings(section = 'server') {
      this.settingsSection = section;
      this.showSettings = false;
      this.view = 'settings';
      this.mobileNavOpen = false;
      await Promise.all([
        this.loadSettings(),
        this.loadAiProfiles(),
        this.loadProxies(),
        this.loadCapabilityAdmin(),
      ]);
    },

    shellTitle() {
      if (this.view === 'newProject') return 'New Project';
      if (this.view === 'settings') return this.settingsSectionTitle();
      if (this.view === 'graph' && this.project?.project) return this.project.project.title || this.project.project.id;
      return 'Projects';
    },

    shellSubtitle() {
      if (this.view === 'newProject') return 'Create project configuration';
      if (this.view === 'settings') return 'Administration and runtime defaults';
      if (this.view === 'graph' && this.project?.project) {
        return `${this.project.project.id} · ${this.project.project.status} · ${this.project.facts.length} facts · ${this.project.intents.length} intents`;
      }
      return `${this.projects.length} projects · ${this.countProjectsByStatus('active')} active`;
    },

    accountLabel() {
      return this.currentUser?.email || this.currentUser?.username || this.currentUser?.name || 'Signed in';
    },

    accountRoleLabel() {
      return this.currentUser?.role || 'account';
    },

    saveSidePanelWidth() {
      try {
        localStorage.setItem('cairn.sidePanelWidth', String(this.sidePanelWidth));
      } catch (e) {
        console.error(e);
      }
    },

    switchSideTab(tab) {
      this.sideTab = tab;
      if (tab === 'capabilities') this.loadCapabilities();
      if (tab === 'files') this.loadProjectFiles(true);
    },

    clampPanelWidth(width) {
      const containerWidth = document.getElementById('graphLayout')?.getBoundingClientRect().width || window.innerWidth;
      const min = 260;
      const max = Math.max(min, containerWidth - 260);
      return Math.min(max, Math.max(min, width));
    },

    startPanelResize(e) {
      e.currentTarget?.setPointerCapture?.(e.pointerId);
      this.isResizingPanel = true;
      this.onPanelResize(e);
    },

    onPanelResize(e) {
      if (!this.isResizingPanel) return;
      this._panelResizePendingEvent = e;
      if (this._panelResizeFrame) return;
      this._panelResizeFrame = requestAnimationFrame(() => {
        this._panelResizeFrame = null;
        const pending = this._panelResizePendingEvent;
        this._panelResizePendingEvent = null;
        this.applyPanelResize(pending);
      });
    },

    applyPanelResize(e) {
      if (!this.isResizingPanel || !e) return;
      const rect = document.getElementById('graphLayout')?.getBoundingClientRect();
      if (!rect) return;
      this.sidePanelWidth = this.clampPanelWidth(rect.right - e.clientX);
    },

    stopPanelResize() {
      if (!this.isResizingPanel) return;
      this.isResizingPanel = false;
      this.saveSidePanelWidth();
      this.settleGraphViewport();
    },

  };
};
