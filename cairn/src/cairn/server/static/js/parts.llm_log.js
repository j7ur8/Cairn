window.CairnParts = window.CairnParts || {};
CairnParts.llm_log = function () {
  return {
    ALL_LLM_EXECUTIONS_VALUE,
    selectedTimelineEntryId: null,
    llmPanelWidth: 320,
    llmPanelCollapsed: false,
    isResizingLlmPanel: false,
    llmExecutions: [],
    llmEvents: [],
    llmLastSequence: 0,
    // Stable project-wide snapshot used only when "All Executions" is selected.
    // This decouples the all-executions view from the rolling 1200-event live window.
    llmAllExecutionEvents: [],
    llmAllExecutionEventsLoading: false,
    llmAllExecutionEventsLoaded: false,
    llmAllExecutionLastSequence: 0,
    llmAllExecutionEventCountLimit: 5000,
    llmEventViewStats: null,
    llmSelectedExecutionId: ALL_LLM_EXECUTIONS_VALUE,
    llmSelectedExecutionEvents: [],
    llmSelectedExecutionEventsLoading: false,
    llmExecutionSelectInteracting: false,
    llmExecutionsRefreshPending: false,
    llmExecutionsLastRefreshAt: 0,
    llmEventContentCache: {},
    // Memoization for filteredLlmEvents() / _llmEventsForView(). Bumped on
    // any input change (event list, per-exec selection, filter).
    // 6+ template call sites in a single render collapse to 1 computation.
    _llmViewVersion: 0,
    _llmViewCache: null,
    _llmViewCacheKey: '',
    _llmEventsForViewCache: null,
    _llmEventsForViewCacheKey: '',
    _llmViewModelCache: null,
    _llmViewModelCacheKey: '',
    // Shared cache of tryParseLlmJsonObject(event.content) results, keyed by
    // event.sequence. Reused by mergeLlmCommandEvents and parseLlmEventContent.
    _llmParsedPayloadCache: new Map(),
    llmEventKindFilter: 'all',
    llmEventKindFilters: LLM_EVENT_KIND_FILTERS,
    llmExpandedEvents: {},
    llmPollTimer: null,
    llmPollInFlight: false,
    llmPollingPaused: false,
    llmLastSlowPollAt: 0,
    llmRenderLimit: 100,
    llmRenderStep: 100,
    showReplayConfigModal: false,
    replayConfig: {
      sourceProjectId: '',
      sourceProjectTitle: '',
      title: '',
      origin: '',
      goal: '',
      hints: [],
      role_id: '',
      capabilities: defaultTaskCapabilitiesMap(),
      ai_profiles: defaultTaskAiProfileSelections(),
      task_timeouts: defaultTaskTimeouts(),
      llm_visible_event_kinds: defaultLlmVisibleEventKinds(),
      catalog: { capabilities: [], roles: [], ai_profiles: [] },
    },
    isCreatingReplayRun: false,
    replayConfigPanel: 'basic',
    replay: {
      active: false,
      playing: false,
      stepMs: '1600',
      frameIndex: -1,
      frames: [],
      visibleEvents: [],
      sourceProject: null,
      timer: null,
    },
    _timelineEventsCacheProject: null,
    _timelineEventsCache: [],
    _timelineViewModelCacheKey: '',
    _timelineViewModelCache: null,
    _llmPanelResizeFrame: null,
    _llmPanelResizePendingEvent: null,
    selectExecutionLog() {
      if (!this.selectedProjectId) return;
      this.view = 'graph';
      this.graphMode = 'log';
      this.mobileNavOpen = false;
    },

    runningExecutionCount() {
      return (this.llmExecutions || []).filter(item => ['running', 'active'].includes(String(item.status || '').toLowerCase())).length;
    },

    errorEventCount() {
      return (this.llmEvents || []).filter(event => String(event.kind || '').toLowerCase().includes('error')).length;
    },

    saveLlmPanelPrefs() {
      try {
        localStorage.setItem('cairn.llmPanelWidth', String(this.llmPanelWidth));
        localStorage.setItem('cairn.llmPanelCollapsed', String(this.llmPanelCollapsed));
      } catch (e) {
        console.error(e);
      }
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
      this.llmAllExecutionEvents = [];
      this.llmAllExecutionEventsLoading = false;
      this.llmAllExecutionEventsLoaded = false;
      this.llmAllExecutionLastSequence = 0;
      this.llmEventViewStats = null;
      this.llmSelectedExecutionId = ALL_LLM_EXECUTIONS_VALUE;
      this.llmSelectedExecutionEvents = [];
      this.llmSelectedExecutionEventsLoading = false;
      this.llmExecutionSelectInteracting = false;
      this.llmExecutionsRefreshPending = false;
      this.llmExecutionsLastRefreshAt = 0;
      this.llmEventContentCache = {};
      this.llmEventKindFilter = 'all';
      this.llmExpandedEvents = {};
      this.llmPollingPaused = false;
      this.llmLastSlowPollAt = 0;
      this._llmViewVersion++;
      this._llmViewCache = null;
      this._llmViewCacheKey = '';
      this._llmEventsForViewCache = null;
      this._llmEventsForViewCacheKey = '';
      this._llmViewModelCache = null;
      this._llmViewModelCacheKey = '';
      this._llmParsedPayloadCache.clear();
    },

    async loadLlmExecutions() {
      if (!this.selectedProjectId || this.view !== 'graph' || !this.project?.project) return;
      try {
        const data = await this.api('GET', `/projects/${this.selectedProjectId}/llm-executions?limit=200`);
        const executions = data.executions || [];
        this.llmExecutionsLastRefreshAt = Date.now();
        if (this.llmExecutionSelectInteracting) {
          this.llmExecutionsRefreshPending = true;
          return;
        }
        this.applyLlmExecutions(executions);
      } catch (e) {
        console.error(e);
      }
    },

    isAllLlmExecutionsSelected() {
      return this.llmSelectedExecutionId === ALL_LLM_EXECUTIONS_VALUE;
    },

    selectedLlmExecutionIdForQuery() {
      return this.isAllLlmExecutionsSelected() ? '' : this.llmSelectedExecutionId;
    },

    applyLlmExecutions(executions) {
      const next = Array.isArray(executions) ? executions : [];
      const sameLength = this.llmExecutions.length === next.length;
      const sameItems = sameLength && this.llmExecutions.every((current, index) => {
        const candidate = next[index];
        if (!candidate) return false;
        return current.id === candidate.id
          && current.process_state === candidate.process_state
          && current.event_count === candidate.event_count
          && current.last_event_at === candidate.last_event_at
          && current.ended_at === candidate.ended_at
          && current.error_kind === candidate.error_kind
          && current.intent_id === candidate.intent_id
          && current.task_type === candidate.task_type
          && current.worker === candidate.worker;
      });
      if (!sameItems) {
        this.llmExecutions = next;
      }
      if (!this.isAllLlmExecutionsSelected() && !next.some(execution => execution.id === this.llmSelectedExecutionId)) {
        this.llmSelectedExecutionId = ALL_LLM_EXECUTIONS_VALUE;
        this.llmSelectedExecutionEvents = [];
        this.llmSelectedExecutionEventsLoading = false;
        this._llmViewVersion++;
      }
      this.llmExecutionsRefreshPending = false;
    },

    beginLlmExecutionSelectionInteraction() {
      this.llmExecutionSelectInteracting = true;
    },

    async endLlmExecutionSelectionInteraction() {
      this.llmExecutionSelectInteracting = false;
      if (!this.llmExecutionsRefreshPending) return;
      await this.loadLlmExecutions();
    },

    handleLlmExecutionSelectionChange() {
      const targetId = this.selectedLlmExecutionIdForQuery();
      this.llmSelectedExecutionEvents = [];
      this.llmEventViewStats = null;
      this.llmSelectedExecutionEventsLoading = false;
      this._llmViewVersion++;
      if (targetId) {
        this.llmSelectedExecutionEventsLoading = true;
      }
      this.$nextTick(() => {
        this.endLlmExecutionSelectionInteraction();
        if (targetId) {
          this.loadLlmExecutionEvents(targetId);
        } else {
          this.loadAllExecutionEvents(true);
        }
      });
    },

    llmEventViewUrl({ executionId = '', after = 0, limit = 300 } = {}) {
      const params = new URLSearchParams();
      params.set('limit', String(limit));
      const visibleKinds = this.currentLlmVisibleEventKinds();
      if (visibleKinds.length === 0) params.append('event_kinds', '');
      for (const kind of visibleKinds) {
        params.append('event_kinds', kind);
      }
      if (executionId) params.set('execution_id', executionId);
      if (after > 0) params.set('after', String(after));
      return `/projects/${this.selectedProjectId}/llm-events/view?${params.toString()}`;
    },

    llmIncrementalEventsUrl({ executionId = '', after = 0, limit = 200 } = {}) {
      const params = new URLSearchParams();
      params.set('limit', String(limit));
      params.set('after', String(after));
      const visibleKinds = this.currentLlmVisibleEventKinds();
      if (visibleKinds.length === 0) params.append('event_kinds', '');
      for (const kind of visibleKinds) {
        params.append('event_kinds', kind);
      }
      if (executionId) params.set('execution_id', executionId);
      return `/projects/${this.selectedProjectId}/llm-events/incremental?${params.toString()}`;
    },

    currentLlmVisibleEventKinds() {
      const projectKinds = this.llmVisibleKindsFromProject(this.project?.project || {});
      const visible = new Set(projectKinds);
      visible.delete('usage');
      return LLM_EVENT_KIND_OPTIONS.filter(kind => visible.has(kind));
    },

    applyLlmEventViewMeta(data) {
      this.llmEventViewStats = data?.stats || null;
      const lastSequence = Number(data?.last_sequence || 0);
      if (Number.isFinite(lastSequence) && lastSequence > 0) {
        this.llmLastSequence = Math.max(this.llmLastSequence, lastSequence);
      }
    },

    mergeLlmEventRows(existing, incoming, limit = 1200) {
      const rows = Array.isArray(incoming) ? incoming : [];
      if (rows.length === 0) return existing;
      const bySequence = new Map(existing.map(event => [event.sequence, event]));
      for (const event of rows) {
        if (event && event.sequence !== undefined && !bySequence.has(event.sequence)) {
          bySequence.set(event.sequence, event);
        }
      }
      const merged = Array.from(bySequence.values())
        .sort((a, b) => this.llmEventSequence(a) - this.llmEventSequence(b))
        .slice(-limit);
      this.pruneLlmCachesForEvents(merged);
      return merged;
    },

    pruneLlmCachesForEvents(events) {
      const keep = new Set((Array.isArray(events) ? events : []).map(event => event.sequence));
      for (const key of this._llmParsedPayloadCache.keys()) {
        if (!keep.has(key)) this._llmParsedPayloadCache.delete(key);
      }
      const nextContentCache = {};
      for (const [key, value] of Object.entries(this.llmEventContentCache || {})) {
        const sequence = Number(String(key).split(':')[0]);
        if (keep.has(sequence)) nextContentCache[key] = value;
      }
      this.llmEventContentCache = nextContentCache;
    },

    async reloadLlmEventView(force = false) {
      if (!this.selectedProjectId || this.view !== 'graph' || !this.project?.project) return;
      const executionId = this.selectedLlmExecutionIdForQuery();
      if (executionId) {
        await this.loadLlmExecutionEvents(executionId);
      } else {
        await this.loadAllExecutionEvents(force);
      }
    },

    async loadLlmExecutionEvents(executionId) {
      if (!this.selectedProjectId || !this.project?.project || !executionId) {
        this.llmSelectedExecutionEventsLoading = false;
        this._llmViewVersion++;
        return;
      }
      try {
        const data = await this.api('GET', this.llmEventViewUrl({ executionId, limit: 300 }));
        const events = Array.isArray(data?.primary_events) ? data.primary_events : [];
        if (this.selectedLlmExecutionIdForQuery() === executionId) {
          this.llmSelectedExecutionEvents = events;
          this.applyLlmEventViewMeta(data);
          this._llmViewVersion++;
        }
      } catch (e) {
        console.error(e);
        if (this.selectedLlmExecutionIdForQuery() === executionId) {
          this.llmSelectedExecutionEvents = [];
          this._llmViewVersion++;
        }
      } finally {
        if (this.selectedLlmExecutionIdForQuery() === executionId) {
          this.llmSelectedExecutionEventsLoading = false;
          this._llmViewVersion++;
        }
      }
    },

    async loadAllExecutionEvents(force = false) {
      if (!this.selectedProjectId || this.view !== 'graph' || !this.project?.project) return;
      if (this.llmAllExecutionEventsLoading) return;
      if (!force && this.llmAllExecutionEventsLoaded) return;
      this.llmAllExecutionEventsLoading = true;
      this._llmViewVersion++;
      try {
        const data = await this.api('GET', this.llmEventViewUrl({ limit: 300 }));
        const rows = Array.isArray(data?.primary_events) ? data.primary_events : [];
        this.llmAllExecutionEvents = rows;
        this.llmAllExecutionLastSequence = Number(data?.last_sequence || 0);
        this.llmLastSequence = Math.max(this.llmLastSequence, this.llmAllExecutionLastSequence);
        this.applyLlmEventViewMeta(data);
        this.llmAllExecutionEventsLoaded = true;
        this._llmViewVersion++;
      } catch (e) {
        console.error(e);
      } finally {
        this.llmAllExecutionEventsLoading = false;
        this._llmViewVersion++;
      }
    },

    async pollLlmEvents(force = false) {
      if (!this.selectedProjectId || this.view !== 'graph' || !this.project?.project || this.replay.active) return;
      if (!force && (this.llmPanelCollapsed || this.llmPollingPaused)) return;
      if (this.llmPollInFlight && !force) return;
      this.llmPollInFlight = true;
      try {
        const after = force && this.llmEvents.length === 0 ? 0 : this.llmLastSequence;
        const selectedExecutionId = this.selectedLlmExecutionIdForQuery();
        const data = await this.api(
          'GET',
          this.llmIncrementalEventsUrl({ executionId: selectedExecutionId, after, limit: 200 }),
        );
        const events = Array.isArray(data?.events) ? data.events : [];
        const lastSequence = Number(data?.last_sequence || 0);
        const hasNewWindow = lastSequence > after;
        if (Number.isFinite(lastSequence) && lastSequence > 0) {
          this.llmLastSequence = Math.max(this.llmLastSequence, lastSequence);
        }
        if (events.length > 0 || hasNewWindow) {
          if (after === 0) {
            this.llmEvents = [];
            if (selectedExecutionId) this.llmSelectedExecutionEvents = [];
          }
          this.llmEvents = this.mergeLlmEventRows(this.llmEvents, events, 1200);

          if (selectedExecutionId) {
            const selectedAppended = events.filter(event => event.execution_id === selectedExecutionId);
            this.llmSelectedExecutionEvents = this.mergeLlmEventRows(this.llmSelectedExecutionEvents, selectedAppended, 1000);
          }

          if (!selectedExecutionId && this.llmAllExecutionEventsLoaded) {
            this.llmAllExecutionEvents = this.mergeLlmEventRows(
              this.llmAllExecutionEvents,
              events,
              this.llmAllExecutionEventCountLimit,
            );
            this.llmAllExecutionLastSequence = Math.max(this.llmAllExecutionLastSequence, lastSequence || 0);
          }

          this._llmViewVersion++;
          await this.loadLlmExecutions();
        } else if (force || this.llmExecutions.some(execution => execution.process_state === 'running')) {
          await this.loadLlmExecutions();
          if (this.llmEvents.length === 0 && this.llmExecutions.length > 0 && after !== 0) {
            this.llmLastSequence = 0;
            await this.pollLlmEvents(true);
          }
        }
      } catch (e) {
        console.error(e);
      } finally {
        this.llmPollInFlight = false;
      }
    },

    startLlmPolling() {
      if (this.llmPollTimer) return;
      this.llmPollTimer = setInterval(async () => {
        if (!this.selectedProjectId || this.view !== 'graph' || !this.project?.project) return;
        if (this.llmPanelCollapsed || this.llmPollingPaused || this.replay.active) return;
        const hasRunning = this.llmExecutions.some(execution => execution.process_state === 'running');
        const now = Date.now();
        if (now - this.llmExecutionsLastRefreshAt >= 2000) {
          await this.loadLlmExecutions();
        }
        if (hasRunning || this.llmEvents.length === 0 || now - this.llmLastSlowPollAt >= 5000) {
          if (!hasRunning) this.llmLastSlowPollAt = now;
          await this.pollLlmEvents();
        }
      }, 1000);
    },

    _llmEventsForView() {
      const cacheKey = `${this._llmViewVersion}:${this.llmSelectedExecutionId || ''}:${this.llmSelectedExecutionEventsLoading ? 1 : 0}:${this.llmSelectedExecutionEvents.length}:${this.llmAllExecutionEventsLoaded ? 1 : 0}:${this.llmAllExecutionEventsLoading ? 1 : 0}:${this.llmAllExecutionEvents.length}`;
      if (this._llmEventsForViewCache && this._llmEventsForViewCacheKey === cacheKey) {
        return this._llmEventsForViewCache;
      }
      let result;
      if (this.isAllLlmExecutionsSelected()) {
        // "All Executions" is backed by the stable complete-history snapshot,
        // not the rolling llmEvents live window.
        result = this.llmAllExecutionEvents;
      } else if (this.llmSelectedExecutionEvents.length > 0 || this.llmSelectedExecutionEventsLoading) {
        result = this.llmSelectedExecutionEvents;
      } else {
        // Fallback while the per-execution fetch has not produced results yet:
        // surface what is already in the rolling 1200-event window so the
        // user does not see an empty pane flash.
        result = this.llmEvents.filter(event => event.execution_id === this.llmSelectedExecutionId);
      }
      this._llmEventsForViewCache = result;
      this._llmEventsForViewCacheKey = cacheKey;
      return result;
    },

    filteredLlmEvents() {
      if (this._llmViewCache && this._llmViewCacheKey === String(this._llmViewVersion)) {
        return this._llmViewCache;
      }
      const events = this._llmEventsForView();
      const result = this.mergeLlmCommandEvents(events.filter(event => this.isVisibleLlmEvent(event)))
        .filter(event => this.matchesLlmEventKindFilter(event))
        .sort((a, b) => this.llmEventSequence(b) - this.llmEventSequence(a))
        .slice(0, 500);
      this._llmViewCache = result;
      this._llmViewCacheKey = String(this._llmViewVersion);
      return result;
    },

    llmViewModel() {
      const cacheKey = `${this._llmViewVersion}:${this.llmRenderLimit}`;
      if (this._llmViewModelCache && this._llmViewModelCacheKey === cacheKey) {
        return this._llmViewModelCache;
      }
      const allEvents = this.filteredLlmEvents();
      const hasFilterHiddenEvents = this._llmEventsForView().length > 0 && allEvents.length === 0;
      const hiddenSummary = this.llmHiddenEventSummary();
      const visibleEvents = allEvents.slice(0, this.llmRenderLimit);
      const model = {
        allEvents,
        events: visibleEvents,
        eventCount: allEvents.length,
        hiddenSummary,
        hasFilterHiddenEvents,
        showEmpty: allEvents.length === 0 && !hasFilterHiddenEvents,
        canLoadMore: allEvents.length > visibleEvents.length,
      };
      this._llmViewModelCache = model;
      this._llmViewModelCacheKey = cacheKey;
      return model;
    },

    showMoreLlmEvents() {
      this.llmRenderLimit = Math.min(
        this.filteredLlmEvents().length,
        this.llmRenderLimit + this.llmRenderStep,
      );
    },

    llmHasFilterHiddenEvents() {
      return this.llmViewModel().hasFilterHiddenEvents;
    },

    llmHasHiddenEvents() {
      return this.llmHasFilterHiddenEvents();
    },

    llmHiddenEventSummary() {
      const hidden = this.llmEventViewStats?.hidden_by_kind || {};
      const parts = Object.entries(hidden)
        .filter(([, count]) => Number(count || 0) > 0)
        .map(([kind, count]) => `${count} ${kind}`);
      return parts.length > 0 ? `Hidden: ${parts.join(' · ')}` : '';
    },

    llmEventSequence(event) {
      const sequence = Number(event?.sequence || 0);
      return Number.isFinite(sequence) ? sequence : 0;
    },

    isVisibleLlmEvent(event) {
      if (event.event_kind !== 'system_event') return true;
      const payload = this.tryParseLlmJsonObject(event.content);
      if (!payload || typeof payload.type !== 'string') return true;
      if (payload.type.startsWith('turn.')) return payload.type === 'turn.completed';
      return true;
    },

    _LLM_CALL_MERGEABLE_KINDS: ['tool_call', 'tool_result', 'command_start', 'command_end'],

    _getParsedPayload(event) {
      const cached = this._llmParsedPayloadCache.get(event.sequence);
      if (cached !== undefined) return cached;
      // tryParseLlmJsonObject returns null for non-JSON content. Distinguish
      // "not yet parsed" (undefined) from "parsed and is null" (null) by
      // storing both — the cache check above handles either.
      const parsed = this.tryParseLlmJsonObject(event.content);
      this._llmParsedPayloadCache.set(event.sequence, parsed === null ? null : parsed);
      return parsed;
    },

    mergeLlmCommandEvents(events) {
      const merged = [];
      const groups = new Map();
      for (const event of events) {
        if (!this._LLM_CALL_MERGEABLE_KINDS.includes(event.event_kind)) {
          merged.push(event);
          continue;
        }
        const payload = this._getParsedPayload(event) || {};
        const key = this.llmCommandEventKey(event, payload);
        if (!key) {
          merged.push(event);
          continue;
        }
        let group = groups.get(key);
        if (!group) {
          group = {
            toolCall: null,
            toolResult: null,
            commandStart: null,
            commandEnd: null,
            toolCallPayload: null,
            toolResultPayload: null,
            commandStartPayload: null,
            commandEndPayload: null,
            firstIndex: merged.length,
          };
          groups.set(key, group);
          merged.push(null); // placeholder, filled in below
        }
        if (event.event_kind === 'tool_call') {
          group.toolCall = event;
          group.toolCallPayload = payload;
        } else if (event.event_kind === 'tool_result') {
          group.toolResult = event;
          group.toolResultPayload = payload;
        } else if (event.event_kind === 'command_start') {
          group.commandStart = event;
          group.commandStartPayload = payload;
        } else if (event.event_kind === 'command_end') {
          group.commandEnd = event;
          group.commandEndPayload = payload;
        }
        merged[group.firstIndex] = this.buildMergedLlmCallEvent(group);
      }
      // Strip the placeholders (only present if every key was unmergeable,
      // which cannot happen — but keep the filter as a safety net).
      return merged.filter(item => item !== null);
    },

    llmCommandEventKey(event, payload) {
      const scope = `${event.execution_id || ''}:${event.phase || ''}`;
      if (payload.item_id) return `${scope}:item:${payload.item_id}`;
      if (payload.call_id) return `${scope}:call:${payload.call_id}`;
      const command = this.llmFieldText('command', payload.command || payload.summary || event.content || '').trim();
      return command ? `${scope}:command:${command}` : '';
    },

    buildMergedLlmCallEvent(group) {
      const {
        toolCall,
        toolResult,
        commandStart,
        commandEnd,
        toolCallPayload,
        toolResultPayload,
        commandStartPayload,
        commandEndPayload,
      } = group;
      // Pick the most informative "source" event for sequence / phase / created_at.
      // Precedence: command_end > tool_result > command_start > tool_call.
      const source = commandEnd || toolResult || commandStart || toolCall;
      const toolPayload = toolCallPayload || {};
      const startPayload = commandStartPayload || {};
      const endPayload = commandEndPayload || {};
      const resultPayload = toolResultPayload || {};

      const payload = {
        ...toolPayload,
        ...startPayload,
        ...endPayload,
        ...resultPayload,
      };

      // Tool name (the LLM's tool identifier, e.g. "exec_command").
      if (toolPayload.tool) payload.tool = toolPayload.tool;

      // Command: prefer command_start, then command_end, then tool_call.arguments.cmd.
      if (!payload.command) {
        if (startPayload.command) payload.command = startPayload.command;
        else if (endPayload.command) payload.command = endPayload.command;
        else if (toolPayload.arguments && typeof toolPayload.arguments === 'object' && toolPayload.arguments.cmd) {
          payload.command = toolPayload.arguments.cmd;
        }
      }

      // Workdir / cwd: prefer command_start.workdir, then command_end.cwd, then tool_call.arguments.workdir.
      if (!payload.workdir) {
        payload.workdir = startPayload.workdir || endPayload.cwd
          || (toolPayload.arguments && typeof toolPayload.arguments === 'object' ? toolPayload.arguments.workdir : undefined)
          || payload.workdir;
      }
      if (!payload.cwd) {
        payload.cwd = endPayload.cwd || startPayload.workdir || payload.workdir;
      }

      // Output fields: command_end wins; tool_result.output is the fallback.
      if (endPayload.output !== undefined) payload.output = endPayload.output;
      else if (resultPayload.output !== undefined && payload.output === undefined) {
        payload.output = resultPayload.output;
      }
      if (endPayload.stdout !== undefined) payload.stdout = endPayload.stdout;
      if (endPayload.stderr !== undefined) payload.stderr = endPayload.stderr;

      // Error / duration / exit_code: prefer command_end, fall back to tool_result.
      if (endPayload.exit_code !== undefined) payload.exit_code = endPayload.exit_code;
      if (endPayload.duration !== undefined) payload.duration = endPayload.duration;
      if (resultPayload.is_error !== undefined && payload.is_error === undefined) {
        payload.is_error = resultPayload.is_error;
      }

      // Status lifecycle.
      if (endPayload.status) {
        payload.status = endPayload.status;
      } else if (commandEnd) {
        payload.status = 'completed';
      } else if (commandStart) {
        payload.status = 'in_progress';
      } else if (toolResult) {
        payload.status = 'completed';
      } else {
        payload.status = 'pending';
      }

      payload.started_sequence = commandStart?.sequence || toolCall?.sequence || null;
      payload.ended_sequence = commandEnd?.sequence || toolResult?.sequence || null;

      // Visible summary: <tool> · <command> when a tool is known, else the command.
      const toolName = toolPayload.tool || '';
      const commandText = this.llmFieldText('command', payload.command || payload.summary || '').trim();
      if (toolName && commandText) payload.summary = `${toolName} · ${commandText}`;
      else if (toolName) payload.summary = toolName;
      else if (commandText) payload.summary = commandText;
      else if (!payload.summary) payload.summary = 'call';

      const contentString = JSON.stringify(payload, null, 2);
      return {
        ...source,
        sequence: source?.sequence,
        event_kind: 'command_end',
        stream: source?.stream || (commandEnd ? 'system' : 'result'),
        content: contentString,
        _merged_call: true,
        // Pre-parsed payload for parseLlmEventContent's fast path. Avoids
        // re-parsing contentString on every render.
        _parsedPayload: payload,
      };
    },

    matchesLlmEventKindFilter(event) {
      const kind = event.event_kind || '';
      // Merged call events (tool_call + command_start + command_end + tool_result
      // collapsed by call_id) are visible under the two related filter pills.
      if (event._merged_call) {
        return ['all', 'tools', 'commands'].includes(this.llmEventKindFilter);
      }
      if (this.llmEventKindFilter === 'all') return true;
      if (this.llmEventKindFilter === 'tools') return ['tool_call', 'tool_result'].includes(kind);
      if (this.llmEventKindFilter === 'commands') return ['command_start', 'command_end'].includes(kind);
      if (this.llmEventKindFilter === 'output') {
        return ['stdout', 'stderr', 'model_response', 'agent_message', 'thinking', 'result', 'prompt', 'capability_manifest'].includes(kind);
      }
      if (this.llmEventKindFilter === 'errors') {
        return ['parse_error', 'trace_parse_error', 'timeout', 'cancelled', 'error'].includes(kind);
      }
      return true;
    },

    llmExecutionCount(state) {
      return this.llmExecutions.filter(execution => execution.process_state === state).length;
    },

    llmErrorCount() {
      return this.llmExecutions.filter(execution => ['failed', 'timeout', 'cancelled', 'stale'].includes(execution.process_state)).length;
    },

    llmPanelSummary() {
      if (this.llmExecutions.length === 0) return 'No executions';
      return `${this.llmExecutions.length} executions · ${this.llmExecutionCount('running')} running`;
    },

    llmExecutionOptionLabel(execution) {
      const stamp = this.formatExecutionStamp(execution.started_at) || '--:--';
      const taskType = execution.task_type || '';
      const intent = execution.intent_id ? ` · ${execution.intent_id}` : '';
      const state = execution.process_state || '';
      const events = Number(execution.event_count || 0);
      const eventText = `${events} events`;

      let taskPadding = '';
      if (taskType === 'reason') taskPadding = '   ';
      else if (taskType === 'explore') taskPadding = '  ';
      // bootstrap => no extra task padding

      const missingIntentPadding = execution.intent_id ? '' : '    ';

      return `${stamp}  ${taskType}${taskPadding}${intent}${missingIntentPadding}  ${state}  ${eventText}`;
    },

    llmEventContentMode(event) {
      return this.parseLlmEventContent(event).mode;
    },

    llmEventParsedCard(event) {
      return this.parseLlmEventContent(event).card || null;
    },

    llmEventParsedCards(event) {
      return this.parseLlmEventContent(event).cards || [];
    },

    parseLlmEventContent(event) {
      // Cheap cache key: events are immutable after insert, and merged
      // events expose their parsed payload directly. Skips the O(content)
      // key construction the old implementation did on every render.
      const cacheKey = `${event.sequence}:${event._merged_call ? 1 : 0}`;
      const cached = this.llmEventContentCache[cacheKey];
      if (cached) return cached;

      // Fast path: merged events have _parsedPayload attached at build time.
      if (event._parsedPayload) {
        const value = {
          mode: 'json_card',
          card: this.buildLlmJsonCard(event, event._parsedPayload),
          cards: [],
        };
        this.llmEventContentCache[cacheKey] = value;
        return value;
      }

      const parsedObject = this._getParsedPayload(event);
      let value;
      if (parsedObject) {
        value = {
          mode: 'json_card',
          card: this.buildLlmJsonCard(event, parsedObject),
          cards: [],
        };
      } else {
        const raw = typeof event.content === 'string' ? event.content : String(event.content || '');
        const parsedLines = this.tryParseLlmJsonLines(raw);
        if (parsedLines.length > 1) {
          value = {
            mode: 'json_lines',
            card: null,
            cards: parsedLines.map((payload, index) => this.buildLlmJsonCard(event, payload, index)),
          };
        } else {
          value = { mode: 'plain_text', card: null, cards: [] };
        }
      }
      this.llmEventContentCache[cacheKey] = value;
      return value;
    },

    tryParseLlmJsonObject(raw) {
      const text = (raw || '').trim();
      if (!text.startsWith('{') || !text.endsWith('}')) return null;
      try {
        const parsed = JSON.parse(text);
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
      } catch {
        return null;
      }
    },

    tryParseLlmJsonLines(raw) {
      const lines = (raw || '')
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean);
      if (lines.length <= 1) return [];
      const parsed = [];
      for (const line of lines) {
        try {
          const value = JSON.parse(line);
          if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
          parsed.push(value);
        } catch {
          return [];
        }
      }
      return parsed;
    },

    buildLlmJsonCard(event, payload, index = 0) {
      const summary = this.deriveLlmPayloadSummary(event, payload, index);
      const inlineFields = [];
      const blockFields = [];
      const used = new Set();

      const addInline = (key, label, value) => {
        if (value === undefined || value === null || value === '') return;
        inlineFields.push({ label, value: this.llmFieldText(key, value) });
        used.add(key);
      };
      const addBlock = (key, label, value) => {
        if (value === undefined || value === null || value === '') return;
        blockFields.push({ label, value: this.llmFieldText(key, value) });
        used.add(key);
      };

      if (event.event_kind === 'tool_call') {
        addInline('tool', 'Tool', payload.tool);
        addInline('call_id', 'Call ID', payload.call_id);
        addBlock('arguments', 'Arguments', payload.arguments);
      } else if (event.event_kind === 'tool_result') {
        addInline('call_id', 'Call ID', payload.call_id);
        addInline('is_error', 'Is Error', payload.is_error);
        addBlock('output', 'Output', payload.output);
      } else if (event.event_kind === 'command_start') {
        addInline('call_id', 'Call ID', payload.call_id);
        addInline('workdir', 'Workdir', payload.workdir || payload.cwd);
        addInline('description', 'Description', payload.description);
        addBlock('command', 'Command', payload.command);
      } else if (event.event_kind === 'command_end') {
        addInline('call_id', 'Call ID', payload.call_id);
        addInline('status', 'Status', payload.status);
        addInline('exit_code', 'Exit Code', payload.exit_code);
        addInline('interrupted', 'Interrupted', payload.interrupted);
        addInline('cwd', 'CWD', payload.cwd || payload.workdir);
        addBlock('command', 'Command', payload.command);
        addBlock('stdout', 'Stdout', payload.stdout);
        addBlock('stderr', 'Stderr', payload.stderr);
        addBlock('output', 'Output', payload.output);
        addBlock('duration', 'Duration', payload.duration);
        // Merged CALL cards surface `description` as the row-1 title via
        // llmEventHeaderText. Mark it used here so the trailing fallback
        // loop does not render a duplicate Description inline field.
        if (payload.description !== undefined && payload.description !== null && payload.description !== '') {
          used.add('description');
        }
      } else if (event.event_kind === 'usage') {
        for (const key of ['type', 'subtype', 'input_tokens', 'output_tokens', 'thinking_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'service_tier', 'model']) {
          if (Object.prototype.hasOwnProperty.call(payload, key)) addInline(key, this.llmFieldLabel(key), payload[key]);
        }
      } else if (event.event_kind === 'session_init') {
        for (const key of ['model', 'cwd', 'session_id', 'permissionMode', 'apiKeySource', 'claude_code_version', 'output_style']) {
          if (Object.prototype.hasOwnProperty.call(payload, key)) addInline(key, this.llmFieldLabel(key), payload[key]);
        }
        for (const key of ['tools', 'mcp_servers', 'slash_commands', 'agents', 'skills', 'plugins']) {
          if (Object.prototype.hasOwnProperty.call(payload, key)) addBlock(key, this.llmFieldLabel(key), payload[key]);
        }
      } else if (event.event_kind === 'api_retry') {
        for (const key of ['attempt', 'max_retries', 'retry_delay_ms', 'error_status', 'error', 'session_id']) {
          if (Object.prototype.hasOwnProperty.call(payload, key)) addInline(key, this.llmFieldLabel(key), payload[key]);
        }
      } else if (event.event_kind === 'capability_manifest') {
        for (const key of ['project_id', 'task_type']) {
          if (Object.prototype.hasOwnProperty.call(payload, key)) addInline(key, this.llmFieldLabel(key), payload[key]);
        }
        for (const key of ['mcp_servers', 'skills', 'unavailable']) {
          if (Object.prototype.hasOwnProperty.call(payload, key)) addBlock(key, this.llmFieldLabel(key), payload[key]);
        }
      } else if (event.event_kind === 'system_event') {
        for (const key of ['type', 'subtype', 'session_id']) {
          if (Object.prototype.hasOwnProperty.call(payload, key)) addInline(key, this.llmFieldLabel(key), payload[key]);
        }
      } else if (event.event_kind === 'trace_parse_error') {
        addBlock('line_preview', 'Line Preview', payload.line_preview);
      }

      for (const [key, value] of Object.entries(payload)) {
        if (key === 'summary' || used.has(key)) continue;
        if (this.llmFieldShouldUseBlock(key, value)) addBlock(key, this.llmFieldLabel(key), value);
        else addInline(key, this.llmFieldLabel(key), value);
      }

      return { summary, inlineFields, blockFields };
    },

    deriveLlmPayloadSummary(event, payload, index = 0) {
      if (typeof payload.summary === 'string' && payload.summary.trim()) return payload.summary.trim();
      if (typeof payload.subtype === 'string' && typeof payload.type === 'string') return `${payload.type}: ${payload.subtype}`;
      if (typeof payload.type === 'string' && typeof payload.role === 'string') return `${payload.type}: ${payload.role}`;
      if (typeof payload.type === 'string' && payload.type) return payload.type;
      if (payload.message && typeof payload.message === 'object') {
        const role = payload.message.role;
        if (typeof role === 'string' && role) return `message: ${role}`;
      }
      if (event.event_kind === 'tool_call' && payload.tool) return `${payload.tool}`;
      if (event.event_kind === 'command_start' || event.event_kind === 'command_end') {
        const commandText = this.llmFieldText('command', payload.command || payload.summary || '');
        if (commandText) return commandText;
      }
      return `${this.llmEventLabel(event)} ${index > 0 ? `#${index + 1}` : ''}`.trim();
    },

    llmFieldShouldUseBlock(key, value) {
      if (['arguments', 'output', 'stdout', 'stderr', 'line_preview', 'content', 'message', 'toolUseResult', 'tools', 'mcp_servers', 'slash_commands', 'agents', 'skills', 'plugins', 'command', 'duration'].includes(key)) return true;
      if (Array.isArray(value)) return true;
      if (value && typeof value === 'object') return true;
      if (typeof value === 'string' && value.length > 160) return true;
      return false;
    },

    llmFieldLabel(key) {
      const labels = {
        call_id: 'Call ID',
        cwd: 'CWD',
        workdir: 'Workdir',
        stdout: 'Stdout',
        stderr: 'Stderr',
        input_tokens: 'Input Tokens',
        output_tokens: 'Output Tokens',
        thinking_tokens: 'Thinking Tokens',
        cache_creation_input_tokens: 'Cache Creation Input Tokens',
        cache_read_input_tokens: 'Cache Read Input Tokens',
        exit_code: 'Exit Code',
        session_id: 'Session ID',
        mcp_servers: 'MCP Servers',
        slash_commands: 'Slash Commands',
        permissionMode: 'Permission Mode',
        apiKeySource: 'API Key Source',
        project_id: 'Project ID',
        task_type: 'Task Type',
        unavailable: 'Unavailable',
      };
      if (labels[key]) return labels[key];
      return key
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, char => char.toUpperCase());
    },

    llmEventKindLabel(kind) {
      return this.llmFieldLabel(kind);
    },

    llmFieldText(key, value) {
      if (value === undefined || value === null) return '';
      if (typeof value === 'boolean') return value ? 'true' : 'false';
      if (Array.isArray(value)) {
        if (key === 'command' && value.every(item => typeof item === 'string' || typeof item === 'number')) {
          return value.map(item => String(item)).join(' ');
        }
        return JSON.stringify(value, null, 2);
      }
      if (typeof value === 'object') return JSON.stringify(value, null, 2);
      return String(value);
    },

    // For CALL cards, the merged payload's description becomes the row-1
    // title and task_type / worker / phase collapse into row 2. Other
    // events keep the original task_type · worker / phase split.
    _llmEventHasDescription(event) {
      if (!event || !event._merged_call) return false;
      const desc = event._parsedPayload && event._parsedPayload.description;
      return typeof desc === 'string' ? desc.trim().length > 0 : !!desc;
    },

    _llmEventDescriptionText(event) {
      const desc = event._parsedPayload && event._parsedPayload.description;
      return typeof desc === 'string' ? desc.trim() : String(desc);
    },

    llmEventHeaderText(event) {
      // CALL cards with a description show it as the title; everything else
      // has no title text in row 1 (just badge + #sequence + time).
      return this._llmEventHasDescription(event)
        ? this._llmEventDescriptionText(event)
        : '';
    },

    llmEventHeaderTitle(event) {
      return this._llmEventHasDescription(event)
        ? this._llmEventDescriptionText(event)
        : '';
    },

    llmEventSubHeaderText(event) {
      if (this._llmEventHasDescription(event)) {
        const parts = [event.task_type, event.worker, event.phase].filter(
          (part) => part !== undefined && part !== null && String(part).length > 0,
        );
        return parts.join(' · ');
      }
      return event.phase || '';
    },

    llmEventLabel(event) {
      if (event._merged_call) return 'Call';
      if (event._merged_command) return 'Command';
      const labels = {
        prompt: 'Prompt',
        stdout: 'Stdout',
        stderr: 'Stderr',
        model_response: 'Result',
        parse_error: 'Parse Error',
        timeout: 'Timeout',
        cancelled: 'Cancelled',
        process_end: 'Process End',
        error: 'Error',
        result: 'Result',
        agent_message: 'Agent',
        thinking: 'Thinking',
        tool_call: 'Tool Call',
        tool_result: 'Tool Result',
        command_start: 'Command Start',
        command_end: 'Command End',
        usage: 'Usage',
        session_init: 'Session Init',
        api_retry: 'API Retry',
        system_event: 'System',
        capability_manifest: 'Capabilities',
        trace_parse_error: 'Trace Parse',
      };
      return labels[event.event_kind] || event.event_kind || 'Event';
    },

    llmEventBadgeClass(event) {
      if (event._merged_call) return 'bg-sky-50 text-sky-700';
      const kind = event.event_kind;
      if (kind === 'prompt') return 'bg-violet-50 text-violet-700';
      if (kind === 'stdout') return 'bg-slate-100 text-slate-700';
      if (kind === 'stderr') return 'bg-amber-50 text-amber-700';
      if (kind === 'model_response' || kind === 'result') return 'bg-teal-50 text-teal-700';
      if (kind === 'agent_message') return 'bg-teal-50 text-teal-700';
      if (kind === 'thinking') return 'bg-indigo-50 text-indigo-700';
      if (kind === 'tool_call' || kind === 'tool_result') return 'bg-sky-50 text-sky-700';
      if (kind === 'command_start' || kind === 'command_end') return 'bg-slate-100 text-slate-700';
      if (kind === 'usage') return 'bg-emerald-50 text-emerald-700';
      if (kind === 'capability_manifest') return 'bg-cyan-50 text-cyan-700';
      if (['session_init', 'api_retry', 'system_event'].includes(kind)) return 'bg-slate-100 text-slate-700';
      if (['parse_error', 'trace_parse_error', 'timeout', 'cancelled', 'error'].includes(kind)) return 'bg-rose-50 text-rose-700';
      return 'bg-sky-50 text-sky-700';
    },

    llmEventBorderClass(event) {
      if (event._merged_call) return 'border-sky-200';
      if (['parse_error', 'trace_parse_error', 'timeout', 'cancelled', 'error'].includes(event.event_kind)) return 'border-rose-200';
      if (event.event_kind === 'stderr') return 'border-amber-200';
      if (event.event_kind === 'capability_manifest') return 'border-cyan-200';
      if (['tool_call', 'tool_result'].includes(event.event_kind)) return 'border-sky-200';
      if (['command_start', 'command_end'].includes(event.event_kind)) return 'border-slate-300';
      return 'border-slate-200';
    },

    llmEventExpanded(event) {
      // Every card is collapsed by default; only explicit user toggles open it.
      return !!this.llmExpandedEvents[event.sequence];
    },

    toggleLlmEvent(sequence) {
      const event = this.llmEvents.find(item => item.sequence === sequence) || { sequence, event_kind: 'manual' };
      this.llmExpandedEvents[sequence] = !this.llmEventExpanded(event);
    },

    toggleLlmPolling() {
      this.llmPollingPaused = !this.llmPollingPaused;
      if (!this.llmPollingPaused) this.pollLlmEvents(true);
    },

    collapseLlmPanel() {
      this.llmPanelCollapsed = true;
      this.saveLlmPanelPrefs();
      this.settleGraphViewport();
    },

    expandLlmPanel() {
      this.llmPanelCollapsed = false;
      this.saveLlmPanelPrefs();
      this.pollLlmEvents(true);
      this.settleGraphViewport();
    },

    replayProgressLabel() {
      if (!this.replay.active || this.replay.frames.length === 0) return 'Replay';
      return `Replay ${Math.min(this.replay.frameIndex + 1, this.replay.frames.length)} / ${this.replay.frames.length}`;
    },

    stopReplayTimer() {
      if (!this.replay.timer) return;
      clearTimeout(this.replay.timer);
      this.replay.timer = null;
    },

    updateReplaySpeed() {
      if (!this.replay.active || !this.replay.playing) return;
      this.stopReplayTimer();
      this.scheduleReplayTick();
    },

    replayEventWeight(event) {
      const type = event?.type;
      if (type === 'reason_started') return 1.6;
      if (type === 'intent_declared') return 1.05;
      if (type === 'intent_running') return 0.75;
      if (type === 'intent_concluded' || type === 'project_completed') return 1.6;
      if (type === 'project_created' || type === 'hint_added') return 0.8;
      return 1.0;
    },

    replayEventDurationMs(event) {
      const base = Number(this.replay.stepMs) || 1100;
      return Math.round(base * this.replayEventWeight(event));
    },

    replayTimelineElapsedDurationMs(events, index) {
      let elapsed = 0;
      for (let i = 0; i < index; i += 1) {
        elapsed += this.replayEventDurationMs(events[i]);
      }
      return elapsed;
    },

    scheduleReplayTick() {
      if (!this.replay.active || !this.replay.playing) return;
      if (this.replay.frameIndex >= this.replay.frames.length - 1) {
        this.replay.playing = false;
        return;
      }
      this.stopReplayTimer();
      const currentFrame = this.replay.frames[this.replay.frameIndex];
      const delay = this.replayEventDurationMs(currentFrame?.event);
      this.replay.timer = setTimeout(() => this.advanceProjectReplay(), delay);
    },

    buildInitialReplayProject(sourceProject) {
      const origin = sourceProject.facts.find(fact => fact.id === 'origin');
      const goal = sourceProject.facts.find(fact => fact.id === 'goal');
      return {
        project: {
          ...this.cloneData(sourceProject.project),
          status: 'active',
          reason: null,
        },
        facts: [origin, goal].filter(Boolean).map(fact => this.cloneData(fact)),
        intents: [],
        hints: [],
      };
    },

    buildReplayFrames(sourceProject, baseEvents) {
      const sourceIntents = new Map(sourceProject.intents.map(intent => [intent.id, intent]));
      const replayEvents = [];

      for (const event of baseEvents) {
        if (event.type !== 'intent_declared' || !event.intentId) {
          replayEvents.push(this.cloneData(event));
          continue;
        }

        const sourceIntent = sourceIntents.get(event.intentId);
        replayEvents.push({
          id: `reason-started-${event.intentId}`,
          type: 'reason_started',
          timestamp: sourceIntent?.created_at || event.timestamp,
          actor: sourceIntent?.creator || event.actor || 'reasoner',
          title: sourceIntent?.id || event.intentId,
          subtitle: this.intentDisplaySubtitle(sourceIntent || {
            id: event.intentId,
            from: event.sourceFactIds || [],
            to: null,
          }),
          summary: sourceIntent?.description || event.summary || '',
          meta: [],
          targetType: 'reason',
          targetId: sourceIntent?.id || event.intentId,
          order: `${event.order}.reason`,
          intentId: sourceIntent?.id || event.intentId,
          producedFactId: null,
          sourceFactIds: [...(sourceIntent?.from || event.sourceFactIds || [])],
        });
        replayEvents.push(this.cloneData(event));
        if (!sourceIntent?.worker) continue;
        replayEvents.push({
          id: `intent-running-${sourceIntent.id}`,
          type: 'intent_running',
          timestamp: sourceIntent.last_heartbeat_at || sourceIntent.created_at,
          actor: sourceIntent.worker,
          title: this.intentDisplayTitle(sourceIntent),
          subtitle: this.intentDisplaySubtitle(sourceIntent),
          summary: sourceIntent.description,
          meta: [],
          targetType: 'intent',
          targetId: sourceIntent.id,
          order: `${event.order}.run`,
          intentId: sourceIntent.id,
          producedFactId: null,
          sourceFactIds: [...sourceIntent.from],
        });
      }

      const replayProject = this.buildInitialReplayProject(sourceProject);
      const frames = [];
      for (const event of replayEvents) {
        this.applyReplayEvent(replayProject, sourceProject, event);
        frames.push({
          event: this.cloneData(event),
          project: this.cloneData(replayProject),
        });
      }

      if (frames.length > 0) {
        frames[frames.length - 1].project.project.status = sourceProject.project.status;
        frames[frames.length - 1].project.project.reason = this.cloneData(sourceProject.project.reason);
      }
      return frames;
    },

    applyReplayEvent(replayProject, sourceProject, event) {
      if (!replayProject || !sourceProject || !event) return;
      const sourceIntent = event.intentId
        ? sourceProject.intents.find(intent => intent.id === event.intentId) || null
        : null;

      if (event.type === 'project_created') {
        replayProject.project.title = sourceProject.project.title;
        replayProject.project.status = 'active';
        return;
      }

      if (event.type === 'hint_added') {
        const hint = sourceProject.hints.find(item => item.id === event.targetId);
        if (hint && !replayProject.hints.some(item => item.id === hint.id)) {
          replayProject.hints.push(this.cloneData(hint));
        }
        return;
      }

      if (event.type === 'reason_started') {
        replayProject.project.reason = {
          worker: event.actor || 'reasoner',
          trigger: 'new_facts',
          started_at: event.timestamp,
          last_heartbeat_at: event.timestamp,
        };
        return;
      }

      if (event.type === 'intent_declared') {
        if (!sourceIntent) return;
        replayProject.project.reason = null;
        if (!replayProject.intents.some(intent => intent.id === sourceIntent.id)) {
          replayProject.intents.push({
            id: sourceIntent.id,
            from: [...sourceIntent.from],
            to: null,
            description: sourceIntent.description,
            creator: sourceIntent.creator,
            worker: null,
            last_heartbeat_at: null,
            created_at: sourceIntent.created_at,
            concluded_at: null,
          });
        }
        return;
      }

      if (event.type === 'intent_running') {
        if (!sourceIntent) return;
        const replayIntent = replayProject.intents.find(intent => intent.id === sourceIntent.id);
        if (!replayIntent) return;
        replayIntent.worker = sourceIntent.worker || sourceIntent.creator;
        replayIntent.last_heartbeat_at = sourceIntent.last_heartbeat_at || sourceIntent.created_at;
        return;
      }

      if (event.type !== 'intent_concluded' && event.type !== 'project_completed') return;
      if (!sourceIntent) return;

      const replayIntent = replayProject.intents.find(intent => intent.id === sourceIntent.id);
      if (replayIntent) {
        replayIntent.to = sourceIntent.to;
        replayIntent.worker = sourceIntent.worker || sourceIntent.creator;
        replayIntent.last_heartbeat_at = sourceIntent.last_heartbeat_at;
        replayIntent.concluded_at = sourceIntent.concluded_at;
      }

      if (event.type === 'project_completed') {
        replayProject.project.status = 'completed';
        return;
      }

      const producedFact = sourceProject.facts.find(fact => fact.id === sourceIntent.to);
      if (producedFact && !replayProject.facts.some(fact => fact.id === producedFact.id)) {
        replayProject.facts.push(this.cloneData(producedFact));
      }
    },

    applyReplayFrame(frameIndex, options = {}) {
      if (!this.replay.active) return;
      const { reinitialize = false } = options;
      const frame = this.replay.frames[frameIndex];
      if (!frame) return;

      this.replay.frameIndex = frameIndex;
      this.project = this.cloneData(frame.project);
      this.replay.visibleEvents = this.replay.frames
        .slice(0, frameIndex + 1)
        .map(item => this.cloneData(item.event))
        .filter(entry => entry.type !== 'reason_started')
        .map((entry, index, list) => ({ ...entry, isLast: index === list.length - 1 }));
      this.invalidateProjectViewCaches();

      if (reinitialize) {
        this.teardownAutoFit();
        if (this.cy) {
          this.cy.destroy();
          this.cy = null;
        }
        this.$nextTick(() => {
          void this.initGraph();
        this.followReplayTimelineTail();
      });
      return;
      }

      this.updateGraph();
      this.followReplayTimelineTail();
    },

    async handleReplayClick() {
      if (!this.project || this.replay.active || !this.selectedProjectId) return;
      if (this.project.project.status === 'completed') {
        await this.openReplayConfig();
        return;
      }
      await this.startProjectReplay();
    },

    async openReplayConfig() {
      if (!this.project || !this.selectedProjectId || this.project.project.status !== 'completed') return;
      try {
        const sourceProject = await this.api('GET', `/projects/${this.selectedProjectId}`);
        const [catalogCapabilities, catalogRoles, projectCapabilities, projectRole, aiProfiles, projectAiProfiles, executionConfigs] = await Promise.all([
          this.api('GET', '/capabilities/catalog'),
          this.api('GET', '/roles/catalog'),
          this.api('GET', `/projects/${this.selectedProjectId}/capabilities`),
          this.api('GET', `/projects/${this.selectedProjectId}/role`),
          this.api('GET', '/ai-profiles'),
          this.api('GET', `/projects/${this.selectedProjectId}/ai-profiles`),
          this.api('GET', `/projects/${this.selectedProjectId}/execution-configs`),
        ]);
        const origin = sourceProject.facts.find(f => f.id === 'origin')?.description || '';
        const goal = sourceProject.facts.find(f => f.id === 'goal')?.description || '';
        const currentRoleId = projectRole?.role?.role_id || '';
        const replayRoleId = (catalogRoles || []).some(role => role.available !== false && role.id === currentRoleId) ? currentRoleId : '';
        this.aiProfiles = aiProfiles || [];
        const availableIds = new Set(this.aiProfiles.filter(p => p.available !== false).map(p => p.id));
        const sourceSelections = projectAiProfiles?.selections || this.defaultTaskAiProfileSelections();
        const replaySelections = this.compactTaskAiProfileSelections(sourceSelections);
        for (const taskType of this.task_types) {
          const selection = replaySelections[taskType];
          selection.primary_profile_id = selection.primary_profile_id && availableIds.has(selection.primary_profile_id)
            ? selection.primary_profile_id : '';
          selection.fallback_profile_ids = (selection.fallback_profile_ids || []).filter(id => availableIds.has(id));
        }
        this.replayConfig = {
          sourceProjectId: this.selectedProjectId,
          sourceProjectTitle: sourceProject.project.title,
          title: `${sourceProject.project.title} Replay`,
          origin,
          goal,
          hints: (sourceProject.hints || []).map(h => ({ content: h.content })),
          role_id: replayRoleId,
          capabilities: this.hydrateReplayCapabilitiesFromSource(projectCapabilities),
          ai_profiles: replaySelections,
          task_timeouts: this.taskTimeoutsFromExecutionConfigs(executionConfigs),
          llm_visible_event_kinds: this.llmVisibleKindsFromProject(sourceProject.project),
          catalog: {
            capabilities: catalogCapabilities || [],
            roles: catalogRoles || [],
            ai_profiles: this.aiProfiles,
          },
        };
        this.ensureAllTaskAiProfilesSelected(this.replayConfig, this.replayConfigAiProfileItems());
        if (this.replayConfig.hints.length === 0) this.replayConfig.hints = [{ content: '' }];
        this.replayConfigPanel = 'basic';
        this.replayConfigCapabilityPanel = 'bootstrap';
        this.showReplayConfigModal = true;
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async createReplayRun() {
      if (this.isCreatingReplayRun || !this.replayConfig.sourceProjectId) return;
      try {
        if (!this.taskAiProfileSelectionsComplete(this.replayConfig, this.replayConfigAiProfileItems())) {
          throw new Error('Select an AI Profile for Bootstrap, Intent, and Reason before creating a replay project.');
        }
        if (!this.taskTimeoutsComplete(this.replayConfig.task_timeouts)) {
          throw new Error('Set all task timeouts to positive seconds before creating the replay project.');
        }
        this.isCreatingReplayRun = true;
        const actor = this.actorName();
        const hints = (this.replayConfig.hints || [])
          .filter(h => h.content?.trim())
          .map(h => ({ content: h.content.trim(), creator: actor }));
        const body = {
          title: this.replayConfig.title,
          origin: this.replayConfig.origin,
          goal: this.replayConfig.goal,
          hints,
          role_id: this.replayConfig.role_id || null,
          capabilities: this.capabilitiesForReplayRun(),
          task_timeouts: this.taskTimeoutsForPayload(this.replayConfig.task_timeouts),
          llm_visible_event_kinds: this.replayConfig.llm_visible_event_kinds || this.defaultLlmVisibleEventKinds(),
        };
        const aiSelections = this.ensureTaskAiProfileSelections(this.replayConfig);
        body.ai_profiles = this.compactTaskAiProfileSelections(aiSelections);
        const data = await this.api('POST', `/projects/${this.replayConfig.sourceProjectId}/replay-runs`, body);
        const replayProjectId = data.project?.project?.id;
        this.showReplayConfigModal = false;
        this.resetReplayConfig();
        await this.loadProjects();
        if (replayProjectId) await this.openProject(replayProjectId);
        this.showToast('Replay project created');
      } catch (e) {
        this.showToast(e.message, 'error');
      } finally {
        this.isCreatingReplayRun = false;
      }
    },

    canCreateReplayRun() {
      return !this.isCreatingReplayRun
        && !!this.replayConfig.title
        && !!this.replayConfig.origin
        && !!this.replayConfig.goal
        && this.taskTimeoutsComplete(this.replayConfig.task_timeouts)
        && this.taskAiProfileSelectionsComplete(this.replayConfig, this.replayConfigAiProfileItems());
    },

    async startProjectReplay() {
      if (!this.project || this.replay.active || !this.selectedProjectId) return;
      try {
        const sourceProject = await this.api('GET', `/projects/${this.selectedProjectId}`);
        const baseEvents = this.timelineEvents().map(event => ({
          ...event,
          meta: [...(event.meta || [])],
          sourceFactIds: [...(event.sourceFactIds || [])],
        }));
        const frames = this.buildReplayFrames(sourceProject, baseEvents);
        if (frames.length === 0) {
          this.showToast('No timeline to replay', 'error');
          return;
        }

        const stepMs = String(this.replay.stepMs || '1100');
        this.stopReplayTimer();
        this.replay = {
          active: true,
          playing: true,
          stepMs,
          frameIndex: -1,
          frames,
          visibleEvents: [],
          sourceProject,
          timer: null,
        };
        this.polling = false;
        this.sideTab = 'log';
        this.selectedNode = null;
        this.selectedFacts = [];
        this.selectedTimelineEntryId = null;
        this.applyReplayFrame(0, { reinitialize: true });
        this.scheduleReplayTick();
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    advanceProjectReplay() {
      if (!this.replay.active) return;
      if (this.replay.frameIndex >= this.replay.frames.length - 1) {
        this.replay.playing = false;
        this.stopReplayTimer();
        return;
      }
      this.applyReplayFrame(this.replay.frameIndex + 1);
      this.scheduleReplayTick();
    },

    toggleProjectReplayPlayback() {
      if (!this.replay.active) return;
      if (this.replay.playing) {
        this.replay.playing = false;
        this.stopReplayTimer();
        return;
      }
      if (this.replay.frameIndex >= this.replay.frames.length - 1) {
        this.restartProjectReplay();
        return;
      }
      this.replay.playing = true;
      this.scheduleReplayTick();
    },

    restartProjectReplay() {
      if (!this.replay.active || this.replay.frames.length === 0) return;
      this.stopReplayTimer();
      this.replay.playing = true;
      this.selectedNode = null;
      this.selectedFacts = [];
      this.selectedTimelineEntryId = null;
      this.applyReplayFrame(0, { reinitialize: true });
      this.scheduleReplayTick();
    },

    async exitProjectReplay() {
      if (!this.replay.active) return;
      const projectId = this.selectedProjectId;
      const stepMs = String(this.replay.stepMs || '1100');
      this.stopReplayTimer();
      this.replay = {
        active: false,
        playing: false,
        stepMs,
        frameIndex: -1,
        frames: [],
        visibleEvents: [],
        sourceProject: null,
        timer: null,
      };
      this.invalidateProjectViewCaches();
      this.polling = true;
      if (!projectId) return;
      await this.loadProject(projectId);
      this.$nextTick(() => {
        this.teardownAutoFit();
        if (this.cy) {
          this.cy.destroy();
          this.cy = null;
        }
        void this.initGraph();
      });
    },

    clampLlmPanelWidth(width) {
      const containerWidth = document.getElementById('graphLayout')?.getBoundingClientRect().width || window.innerWidth;
      const min = 280;
      const max = Math.min(520, Math.max(min, containerWidth - 520));
      return Math.min(max, Math.max(min, width));
    },

    startLlmPanelResize(e) {
      e.currentTarget?.setPointerCapture?.(e.pointerId);
      this.isResizingLlmPanel = true;
      this.onLlmPanelResize(e);
    },

    onLlmPanelResize(e) {
      if (!this.isResizingLlmPanel) return;
      this._llmPanelResizePendingEvent = e;
      if (this._llmPanelResizeFrame) return;
      this._llmPanelResizeFrame = requestAnimationFrame(() => {
        this._llmPanelResizeFrame = null;
        const pending = this._llmPanelResizePendingEvent;
        this._llmPanelResizePendingEvent = null;
        this.applyLlmPanelResize(pending);
      });
    },

    applyLlmPanelResize(e) {
      if (!this.isResizingLlmPanel || !e) return;
      const rect = document.getElementById('graphLayout')?.getBoundingClientRect();
      if (!rect) return;
      this.llmPanelWidth = this.clampLlmPanelWidth(e.clientX - rect.left);
    },

    stopLlmPanelResize() {
      if (!this.isResizingLlmPanel) return;
      this.isResizingLlmPanel = false;
      this.saveLlmPanelPrefs();
      this.settleGraphViewport();
    },

    parseReplaySummary(text) {
      const trimmed = (text || '').trim();
      if (!trimmed || !trimmed.includes('Original task:')) return null;
      const lines = trimmed.split('\n');
      const sections = {};
      let current = 'headline';
      sections[current] = [];
      for (const line of lines) {
        if (/^Original task:\s*$/.test(line)) {
          current = 'original_task';
          sections[current] = [];
          continue;
        }
        if (/^Expected source fact:\s*/.test(line)) {
          current = 'expected_source_fact';
          sections[current] = [line.replace(/^Expected source fact:\s*/, '').trim()];
          continue;
        }
        if (/^Expected result to reproduce:\s*$/.test(line)) {
          current = 'expected_result';
          sections[current] = [];
          continue;
        }
        if (/^Do not simply restate the expected result;/.test(line)) {
          current = 'instruction';
          sections[current] = [line.trim()];
          continue;
        }
        if (!sections[current]) sections[current] = [];
        sections[current].push(line);
      }

      const headline = (sections.headline || []).join(' ').trim();
      const meta = {};
      if (sections.expected_source_fact?.[0]) meta.expected_source_fact = sections.expected_source_fact[0];
      const bodyParts = [];
      if ((sections.original_task || []).join('\n').trim()) {
        bodyParts.push(`Original task:\n${sections.original_task.join('\n').trim()}`);
      }
      if ((sections.expected_result || []).join('\n').trim()) {
        bodyParts.push(`Expected result to reproduce:\n${sections.expected_result.join('\n').trim()}`);
      }
      if ((sections.instruction || []).join('\n').trim()) {
        bodyParts.push(`Replay instruction:\n${sections.instruction.join('\n').trim()}`);
      }
      return {
        mode: 'replay',
        headline,
        body: bodyParts.join('\n\n').trim(),
        meta,
        raw: trimmed,
      };
    },

    timelineSummaryKind(entry) {
      if (!entry) return 'plain';
      if (entry.type === 'intent_declared' || entry.type === 'intent_running') return 'intent';
      if (entry.type === 'reason_started') return 'reason';
      if (entry.type === 'intent_concluded' || entry.type === 'project_completed') return 'fact';
      return 'plain';
    },

    timelineEvents() {
      if (this.replay.active) return this.replay.visibleEvents;
      if (!this.project) return [];
      if (this._timelineEventsCacheProject === this.project) return this._timelineEventsCache;

      const events = [];
      let order = 0;
      const origin = this.getFactRecord('origin');
      const goal = this.getFactRecord('goal');

      events.push({
        id: `project-created-${this.project.project.id}`,
        type: 'project_created',
        timestamp: this.project.project.created_at,
        actor: 'system',
        title: this.project.project.title,
        meta: [origin ? origin.description : null, goal ? `goal: ${goal.description}` : null].filter(Boolean),
        targetType: 'fact',
        targetId: 'origin',
        order: order++,
        intentId: null,
        producedFactId: null,
        sourceFactIds: [],
      });

      for (const hint of this.project.hints) {
        events.push({
          id: `hint-${hint.id}`,
          type: 'hint_added',
          timestamp: hint.created_at,
          actor: hint.creator,
          title: hint.content,
          meta: [],
          targetType: 'hints',
          targetId: hint.id,
          order: order++,
          intentId: null,
          producedFactId: null,
          sourceFactIds: [],
        });
      }

      for (const intent of this.project.intents) {
        events.push({
          id: `intent-declared-${intent.id}`,
          type: 'intent_declared',
          timestamp: intent.created_at,
          actor: intent.creator,
          title: this.intentDisplayTitle(intent),
          subtitle: this.intentDisplaySubtitle(intent),
          summary: intent.description,
          meta: [],
          targetType: 'intent',
          targetId: intent.id,
          order: order++,
          intentId: intent.id,
          producedFactId: null,
          sourceFactIds: [...intent.from],
        });

        if (!intent.concluded_at || !intent.to) continue;

        if (intent.to === 'goal') {
          const goalFact = this.getFactRecord('goal') || { id: 'goal' };
          events.push({
            id: `project-completed-${intent.id}`,
            type: 'project_completed',
            timestamp: intent.concluded_at,
            actor: intent.worker || intent.creator,
            title: this.factDisplayTitle(goalFact),
            subtitle: `From: ${intent.id}`,
            summary: goalFact.description || intent.description,
            meta: [],
            targetType: 'fact',
            targetId: 'goal',
            order: order++,
            intentId: intent.id,
            producedFactId: 'goal',
            sourceFactIds: [...intent.from],
          });
          continue;
        }

        const fact = this.getFactRecord(intent.to);
        events.push({
          id: `intent-concluded-${intent.id}`,
          type: 'intent_concluded',
          timestamp: intent.concluded_at,
          actor: intent.worker || intent.creator,
          title: this.factDisplayTitle(fact || { id: intent.to }),
          subtitle: `From: ${intent.id}`,
          summary: fact?.description || intent.description,
          meta: [],
          targetType: 'fact',
          targetId: intent.to,
          order: order++,
          intentId: intent.id,
          producedFactId: intent.to,
          sourceFactIds: [...intent.from],
        });
      }

      const chronological = [...events].sort((a, b) =>
        a.timestamp.localeCompare(b.timestamp) || a.order - b.order
      );

      const resolved = [];
      for (let i = 0; i < chronological.length;) {
        const bucket = [chronological[i]];
        let j = i + 1;
        while (j < chronological.length && chronological[j].timestamp === chronological[i].timestamp) {
          bucket.push(chronological[j]);
          j += 1;
        }
        resolved.push(...this.resolveTimelineBucket(bucket));
        i = j;
      }

      const cached = resolved.map((entry, index) => ({ ...entry, isLast: index === resolved.length - 1 }));
      this._timelineEventsCacheProject = this.project;
      this._timelineEventsCache = cached;
      return cached;
    },

    timelineViewModel() {
      const events = this.timelineEvents();
      const cacheKey = [
        this.replay.active ? 'replay' : 'project',
        this.project?.project?.id || '',
        this.project?.project?.updated_at || '',
        events.length,
        events[0]?.id || '',
        events[events.length - 1]?.id || '',
        this.selectedTimelineEntryId || '',
        this.selectedNode?.type || '',
        this.selectedNode?.id || '',
        this.selectedFacts.join(','),
      ].join('|');
      if (this._timelineViewModelCache && this._timelineViewModelCacheKey === cacheKey) {
        return this._timelineViewModelCache;
      }
      const latestEntryId = events.length > 0 ? events[events.length - 1].id : null;
      const model = {
        events,
        empty: events.length === 0,
        latestEntryId,
      };
      this._timelineViewModelCache = model;
      this._timelineViewModelCacheKey = cacheKey;
      return model;
    },

    resolveTimelineBucket(bucket) {
      if (bucket.length <= 1) return bucket;

      const eventById = new Map(bucket.map(event => [event.id, event]));
      const declareEventIdByIntent = new Map();
      const produceEventIdByFact = new Map();
      const outgoing = new Map(bucket.map(event => [event.id, new Set()]));
      const incomingCount = new Map(bucket.map(event => [event.id, 0]));

      const addDependency = (beforeId, afterId) => {
        if (!beforeId || !afterId || beforeId === afterId) return;
        const deps = outgoing.get(beforeId);
        if (!deps || deps.has(afterId)) return;
        deps.add(afterId);
        incomingCount.set(afterId, (incomingCount.get(afterId) || 0) + 1);
      };

      for (const event of bucket) {
        if (event.type === 'intent_declared') declareEventIdByIntent.set(event.intentId, event.id);
        if (event.producedFactId) produceEventIdByFact.set(event.producedFactId, event.id);
      }

      for (const event of bucket) {
        if ((event.type === 'intent_concluded' || event.type === 'project_completed') && event.intentId) {
          addDependency(declareEventIdByIntent.get(event.intentId), event.id);
        }

        if (!event.sourceFactIds?.length) continue;
        for (const factId of event.sourceFactIds) {
          addDependency(produceEventIdByFact.get(factId), event.id);
        }
      }

      const ready = bucket
        .filter(event => incomingCount.get(event.id) === 0)
        .sort((a, b) => a.order - b.order);
      const ordered = [];

      while (ready.length > 0) {
        const event = ready.shift();
        ordered.push(event);
        for (const nextId of outgoing.get(event.id) || []) {
          incomingCount.set(nextId, incomingCount.get(nextId) - 1);
          if (incomingCount.get(nextId) === 0) {
            ready.push(eventById.get(nextId));
            ready.sort((a, b) => a.order - b.order);
          }
        }
      }

      if (ordered.length === bucket.length) return ordered;

      const remainingIds = bucket
        .filter(event => !ordered.some(placed => placed.id === event.id))
        .sort((a, b) => a.order - b.order);
      return [...ordered, ...remainingIds];
    },

    timelineEventBadge(entry) {
      const labels = {
        project_created: 'Project',
        hint_added: 'Hint',
        reason_started: 'Reason',
        intent_declared: 'Intent',
        intent_running: 'Execute',
        intent_concluded: 'Conclude',
        project_completed: 'Complete',
      };
      return labels[entry.type] || 'Event';
    },

    timelineEventBadgeClass(entry) {
      const classes = {
        project_created: 'bg-slate-100 text-slate-600',
        hint_added: 'bg-amber-50 text-amber-700',
        reason_started: 'bg-sky-50 text-sky-700',
        intent_declared: 'bg-violet-50 text-violet-700',
        intent_running: 'bg-amber-50 text-amber-700',
        intent_concluded: 'bg-teal-50 text-teal-700',
        project_completed: 'bg-rose-50 text-rose-700',
      };
      return classes[entry.type] || 'bg-slate-100 text-slate-600';
    },

    timelineEventIsInteractive(entry) {
      return entry?.targetType === 'fact' || entry?.targetType === 'intent' || entry?.targetType === 'hints' || entry?.targetType === 'reason';
    },

    timelineEventTriggersGraphFocus(entry) {
      return entry?.targetType === 'fact' || entry?.targetType === 'intent';
    },

    timelineEventDotClass(entry) {
      const classes = {
        project_created: 'bg-slate-400',
        hint_added: 'bg-amber-400',
        reason_started: 'bg-sky-400',
        intent_declared: 'bg-violet-400',
        intent_running: 'bg-amber-400',
        intent_concluded: 'bg-teal-400',
        project_completed: 'bg-rose-400',
      };
      return classes[entry.type] || 'bg-slate-300';
    },

    timelineEntryButtonClass(entry) {
      const base = this.timelineEventIsInteractive(entry) ? 'cursor-pointer hover:bg-slate-50/70' : 'cursor-default';
      return this.timelineEntryIsSelected(entry)
        ? `${base} bg-brand-50/80 ring-1 ring-brand-200`
        : base;
    },

    timelineEntryDomId(entryId) {
      return `timeline-entry-${entryId}`;
    },

    timelineEntryElement(entryId) {
      return document.getElementById(this.timelineEntryDomId(entryId));
    },

    timelineTargetEntryIdForGraphSelection(allowMultiFact = false) {
      const events = this.timelineEvents();
      if (this.selectedNode?.type === 'intent') {
        const selectedIntentId = this.selectedNode.id;
        return events.find(entry => entry.type === 'intent_declared' && entry.intentId === selectedIntentId)?.id
          || events.find(entry => entry.intentId === selectedIntentId)?.id
          || null;
      }

      if (this.selectedNode?.type === 'fact') {
        if (!allowMultiFact && this.selectedFacts.length > 1) return null;
        const selectedFactId = this.selectedNode.id;
        return events.find(entry => entry.targetType === 'fact' && entry.targetId === selectedFactId)?.id || null;
      }

      return null;
    },

    activeTimelineEntryId(allowMultiFact = false) {
      return this.selectedTimelineEntryId || this.timelineTargetEntryIdForGraphSelection(allowMultiFact);
    },

    latestTimelineEntryId() {
      const events = this.timelineEvents();
      return events.length > 0 ? events[events.length - 1].id : null;
    },

    timelineEntryIsSelected(entry) {
      return !!entry && this.activeTimelineEntryId(false) === entry.id;
    },

    selectedTimelineSummary() {
      const targetEntryId = this.activeTimelineEntryId(false);
      if (!targetEntryId) return null;

      const events = this.timelineEvents();
      const index = events.findIndex(entry => entry.id === targetEntryId);
      if (index < 0) return null;

      const entry = events[index];
      const total = events.length;
      const sequencePercent = total <= 1 ? 100 : Math.round((index / (total - 1)) * 100);
      const replayMode = this.replay.active;
      const totalDuration = replayMode
        ? this.replayTimelineElapsedDurationMs(events, Math.max(0, total - 1))
        : Math.max(0, Date.parse(events[total - 1].timestamp) - Date.parse(events[0].timestamp));
      const elapsedDuration = replayMode
        ? this.replayTimelineElapsedDurationMs(events, index)
        : Math.max(0, Date.parse(entry.timestamp) - Date.parse(events[0].timestamp));
      const timePercent = totalDuration === 0 ? 100 : Math.round((elapsedDuration / totalDuration) * 100);

      return {
        sequencePercent,
        sequenceLabel: `${index + 1} / ${total} · ${sequencePercent}%`,
        timePercent,
        timeLabel: `${this.formatDurationMs(elapsedDuration)} / ${this.formatDurationMs(totalDuration)} · ${timePercent}%`,
      };
    },

    scrollTimelineToEntry(entryId, options = {}) {
      const { flash = true } = options;
      if (!entryId) return;
      this.$nextTick(() => {
        requestAnimationFrame(() => {
          const entry = this.timelineEntryElement(entryId);
          if (!entry) return;
          const panel = entry.closest('.overflow-y-auto');
          if (!panel) return;
          const top = entry.offsetTop - panel.clientHeight / 2 + entry.clientHeight / 2;
          const targetTop = Math.max(0, top);
          panel.scrollTo({ top: targetTop, behavior: 'smooth' });
          if (!flash) return;
          const travel = Math.abs(panel.scrollTop - targetTop);
          const flashDelay = Math.min(450, Math.max(140, travel * 0.18));
          setTimeout(() => {
            entry.classList.remove('timeline-flash');
            void entry.offsetWidth;
            entry.classList.add('timeline-flash');
            setTimeout(() => entry.classList.remove('timeline-flash'), 1000);
          }, flashDelay);
        });
      });
    },

    followReplayTimelineTail() {
      if (!this.replay.active || this.sideTab !== 'log') return;
      this.scrollTimelineToEntry(this.latestTimelineEntryId(), { flash: false });
    },

    scrollTimelineToSelection() {
      if (this.sideTab !== 'log') return;
      this.scrollTimelineToEntry(this.activeTimelineEntryId(true));
    },

    openHintTimelineEntry(hintId) {
      if (!hintId) return;
      const entry = this.timelineEvents().find(event => event.type === 'hint_added' && event.targetId === hintId);
      if (!entry) return;
      this.sideTab = 'log';
      this.openTimelineEntry(entry);
      this.scrollTimelineToEntry(entry.id);
    },

    openTimelineEntry(entry, options = {}) {
      const { centerGraph = true } = options;
      if (!entry || !this.timelineEventIsInteractive(entry)) return;
      if (!this.timelineEventTriggersGraphFocus(entry)) {
        this.selectedTimelineEntryId = entry.id;
        this.clearGraphSelection(true);
        return;
      }
      if (entry.targetType === 'intent' && entry.targetId) {
        this.selectIntent(entry.targetId);
        this.selectedTimelineEntryId = entry.id;
        if (centerGraph) this.centerGraphOnIntent(entry.targetId);
        return;
      }
      if (entry.targetType === 'fact' && entry.targetId) {
        this.selectedFacts = [entry.targetId];
        this.selectFact(entry.targetId);
        this.selectedTimelineEntryId = entry.id;
        if (centerGraph) this.centerGraphOnFact(entry.targetId);
      }
    },

    formatExecutionStamp(ts) {
      if (!ts) return '';
      const d = new Date(ts);
      if (Number.isNaN(d.getTime())) return '';
      const pad = (n) => String(n).padStart(2, '0');
      return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    },
    formatTimelineDate(ts) { if (!ts) return ''; return new Date(ts).toLocaleDateString([],{year:'numeric',month:'short',day:'numeric'}); },
  };
};
