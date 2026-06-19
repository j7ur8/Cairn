import {
  isFiniteNumber,
  parseBooleanPref,
  parseFlagPref,
  parseJsonPref,
  parseNumberPref,
  readPref,
  serializeFlagPref,
  serializeJsonPref,
  writePref,
} from '../shared/prefs.js';

export function createWorkspaceUiState() {
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
      const localPrefs = readPref('cairn.localPrefs', {}, {
        parse: parseJsonPref,
        validate: value => value && typeof value === 'object' && !Array.isArray(value),
      });
      if (typeof localPrefs.actor_name === 'string') this.localPrefs.actor_name = localPrefs.actor_name;
      if (typeof localPrefs.layout_mode === 'string') this.localPrefs.layout_mode = localPrefs.layout_mode;
      this.sidePanelWidth = readPref('cairn.sidePanelWidth', this.sidePanelWidth, {
        parse: parseNumberPref,
        validate: isFiniteNumber,
      });
      this.llmPanelWidth = readPref('cairn.llmPanelWidth', this.llmPanelWidth, {
        parse: parseNumberPref,
        validate: isFiniteNumber,
      });
      this.llmPanelCollapsed = readPref('cairn.llmPanelCollapsed', false, { parse: parseBooleanPref });
      this.navCollapsed = readPref('cairn.navCollapsed', false, { parse: parseFlagPref });
      if (!this.localPrefs.actor_name.trim()) this.localPrefs.actor_name = 'Human';
      if (!this.isValidLayoutMode(this.localPrefs.layout_mode)) this.localPrefs.layout_mode = 'dagre_tb';
      this.layoutMode = this.localPrefs.layout_mode;
    },

    saveLocalPrefs() {
      writePref('cairn.localPrefs', this.localPrefs, { serialize: serializeJsonPref });
    },

    saveNavPrefs() {
      writePref('cairn.navCollapsed', this.navCollapsed, { serialize: serializeFlagPref });
    },

    appShellVisible() {
      return this.appBootstrapped && !this.showLogin;
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
        return `${this.project.project.id} · ${this.project.project.status} · ${this.projectFactCount()} facts · ${this.projectIntentCount()} intents`;
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
      writePref('cairn.sidePanelWidth', this.sidePanelWidth);
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
}
