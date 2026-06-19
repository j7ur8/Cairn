import { ALL_LLM_EXECUTIONS_VALUE, LLM_EVENT_KIND_OPTIONS } from '../../shared/constants.js';
import { serializeBooleanPref, writePref } from '../../shared/prefs.js';

export function createWorkspaceLogBaseActions() {
  return {
    llmExecutionState(execution) {
      return String(execution?.process_state || execution?.status || '').toLowerCase();
    },

    llmExecutionIsRunning(execution) {
      return ['running', 'active'].includes(this.llmExecutionState(execution));
    },

    llmExecutionCount(state) {
      const target = String(state || '').toLowerCase();
      return (this.llmExecutions || []).filter(execution => this.llmExecutionState(execution) === target).length;
    },

    llmErrorCount() {
      const errorStates = ['failed', 'timeout', 'cancelled', 'stale'];
      return (this.llmExecutions || []).filter(execution => errorStates.includes(this.llmExecutionState(execution))).length;
    },

    llmPanelSummary() {
      return `${this.llmExecutions.length} executions · ${this.llmExecutionCount('running')} running · ${this.llmErrorCount()} errors`;
    },

    runningExecutionCount() {
      return (this.llmExecutions || []).filter(item => this.llmExecutionIsRunning(item)).length;
    },

    errorEventCount() {
      return (this.llmEvents || []).filter(event => String(event.kind || '').toLowerCase().includes('error')).length;
    },

    saveLlmPanelPrefs() {
      writePref('cairn.llmPanelWidth', this.llmPanelWidth);
      writePref('cairn.llmPanelCollapsed', this.llmPanelCollapsed, { serialize: serializeBooleanPref });
    },

    highlightTimeline(text) {
      const lines = String(text ?? '').split('\n');
      const stripes = ['#fffbf5', '#fef5ee'];
      let blockIndex = -1;
      return lines.map((line) => {
        if (/^\[/.test(line)) blockIndex++;
        const bg = blockIndex < 0 ? stripes[0] : stripes[blockIndex % 2];
        const isBlank = /^\s*$/.test(line);
        return `<div style="white-space:pre;padding:0 16px;background:${bg};color:#0f172a">${isBlank ? '&nbsp;' : this.escapeHtml(line)}</div>`;
      }).join('');
    },

    defaultLlmVisibleEventKinds() {
      return LLM_EVENT_KIND_OPTIONS.filter(kind => kind !== 'usage');
    },

    llmEventKindOptions() {
      return LLM_EVENT_KIND_OPTIONS;
    },

    llmVisibleKindSelected(target, kind) {
      return Array.isArray(target?.llm_visible_event_kinds)
        && target.llm_visible_event_kinds.includes(kind);
    },

    toggleLlmVisibleKind(target, kind, checked) {
      if (!target) return;
      const current = Array.isArray(target.llm_visible_event_kinds)
        ? target.llm_visible_event_kinds : this.defaultLlmVisibleEventKinds();
      const selected = new Set(current);
      if (checked) selected.add(kind);
      else selected.delete(kind);
      target.llm_visible_event_kinds = LLM_EVENT_KIND_OPTIONS.filter(item => selected.has(item));
    },

    llmVisibleKindsFromProject(projectMeta) {
      const hidden = new Set(Array.isArray(projectMeta?.llm_hidden_event_kinds) ? projectMeta.llm_hidden_event_kinds : ['usage']);
      return LLM_EVENT_KIND_OPTIONS.filter(kind => !hidden.has(kind));
    },

    resetReplayConfig() {
      this.replayConfig = {
        sourceProjectId: '',
        sourceProjectTitle: '',
        title: '',
        origin: '',
        goal: '',
        hints: [],
        role_id: '',
        capabilities: this.defaultTaskCapabilitiesMap(),
        ai_profiles: this.defaultTaskAiProfileSelections(),
        task_timeouts: this.defaultTaskTimeouts(),
        llm_visible_event_kinds: this.defaultLlmVisibleEventKinds(),
        catalog: { capabilities: [], roles: [], ai_profiles: [] },
      };
      this.replayConfigPanel = 'basic';
      this.replayConfigCapabilityPanel = 'bootstrap';
    },

    replayConfigRoleItems() {
      return (this.replayConfig.catalog?.roles || []).filter(item => item.available !== false);
    },

    resetLlmState() {
      this.llmExecutions = [];
      this.llmEvents = [];
      this.llmLastSequence = 0;
      this.llmLatestEvents = [];
      this.llmLatestLoading = false;
      this.llmPagedEvents = [];
      this.llmPageToken = '';
      this.llmPageTokenHistory = [];
      this.llmPageNextToken = '';
      this.llmPageHasNext = false;
      this.llmPageLoading = false;
      this.llmPageRangeLabel = '';
      this.llmEventViewStats = null;
      this.llmSelectedExecutionId = ALL_LLM_EXECUTIONS_VALUE;
      this.llmExecutionSelectInteracting = false;
      this.llmExecutionsRefreshPending = false;
      this.llmExecutionsLastRefreshAt = 0;
      this.llmEventContentCache = {};
      this.llmEventKindFilter = 'all';
      this.llmExpandedEvents = {};
      this.llmPollingPaused = false;
      this.llmLastSlowPollAt = 0;
      this.llmLastEventPollAt = 0;
      this.timelineRenderLimit = 200;
      this.llmPerfStats.incrementalPolls = 0;
      this.llmPerfStats.executionPolls = 0;
      this.llmPerfStats.filteredCalls = 0;
      this.llmPerfStats.filteredMs = 0;
      this.llmPerfStats.lastEventWindowSize = 0;
      this.llmPerfStats.longTasks = 0;
      this.llmPerfStats.lastLogAt = 0;
      this._llmViewVersion++;
      this._llmViewCache = null;
      this._llmViewCacheKey = '';
      this._llmViewModelCache = null;
      this._llmViewModelCacheKey = '';
      this._llmLatestRequestToken++;
      this._llmPageRequestToken++;
      clearTimeout(this._llmPageResizeTimer);
      this._llmPageResizeTimer = null;
      this._llmParsedPayloadCache.clear();
    },
  };
}
