import { ALL_LLM_EXECUTIONS_VALUE, LLM_EVENT_KIND_OPTIONS } from '../../shared/constants.js';

export function llmBackendKindsForFilter(filterId, visibleKinds, allKinds = LLM_EVENT_KIND_OPTIONS) {
  const visible = new Set(Array.isArray(visibleKinds) ? visibleKinds : []);
  const allowed = kind => allKinds.includes(kind) && visible.has(kind);
  let candidates;
  if (filterId === 'tools') {
    candidates = ['tool_call', 'tool_result', 'command_start', 'command_end'];
  } else if (filterId === 'commands') {
    candidates = ['tool_call', 'tool_result', 'command_start', 'command_end'];
  } else if (filterId === 'output') {
    candidates = ['stdout', 'stderr', 'model_response', 'agent_message', 'thinking', 'result', 'prompt', 'capability_manifest'];
  } else if (filterId === 'errors') {
    candidates = ['parse_error', 'trace_parse_error', 'timeout', 'cancelled', 'error'];
  } else {
    candidates = allKinds;
  }
  return candidates.filter(allowed);
}

export function llmPageWindow(rows, pageSize) {
  const safeRows = Array.isArray(rows) ? rows : [];
  const safeSize = Math.max(1, Number(pageSize || 1));
  return {
    rows: safeRows.slice(0, safeSize),
    hasNext: safeRows.length > safeSize,
  };
}

export function nextLlmPageCursor(displayedEvents) {
  const rows = Array.isArray(displayedEvents) ? displayedEvents : [];
  const last = rows[rows.length - 1];
  const sequence = Number(last?.sequence || 0);
  return Number.isFinite(sequence) && sequence > 0 ? sequence : 0;
}

export function createWorkspaceLogEventState() {
  return {
    async loadLlmExecutions(force = false) {
      if (!this.selectedProjectId || this.view !== 'graph' || !this.project?.project) return;
      const now = Date.now();
      const refreshMs = this.llmExecutionRefreshMs();
      if (!force && now - this.llmExecutionsLastRefreshAt < refreshMs) return;
      try {
        this.llmPerfStats.executionPolls++;
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
        this.resetLlmEventPagination();
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
      await this.loadLlmExecutions(true);
    },

    handleLlmExecutionSelectionChange() {
      this.llmEventViewStats = null;
      this._llmViewVersion++;
      this.$nextTick(() => {
        this.endLlmExecutionSelectionInteraction();
        this.resetLlmEventPagination();
      });
    },

    llmEventViewUrl({ executionId = '', after = 0, limit = 300, includeEventKinds = true } = {}) {
      const params = new URLSearchParams();
      params.set('limit', String(limit));
      if (includeEventKinds) {
        const visibleKinds = this.currentLlmBackendEventKinds();
        if (visibleKinds.length === 0) params.append('event_kinds', '');
        for (const kind of visibleKinds) {
          params.append('event_kinds', kind);
        }
      }
      if (executionId) params.set('execution_id', executionId);
      if (after > 0) params.set('after', String(after));
      return `/projects/${this.selectedProjectId}/llm-events/view?${params.toString()}`;
    },

    llmIncrementalEventsUrl({ executionId = '', after = 0, limit = 200 } = {}) {
      const params = new URLSearchParams();
      params.set('limit', String(limit));
      params.set('after', String(after));
      const visibleKinds = this.currentLlmBackendEventKinds();
      if (visibleKinds.length === 0) params.append('event_kinds', '');
      for (const kind of visibleKinds) {
        params.append('event_kinds', kind);
      }
      if (executionId) params.set('execution_id', executionId);
      return `/projects/${this.selectedProjectId}/llm-events/incremental?${params.toString()}`;
    },

    llmEventCardsUrl({ executionId = '', pageSize = this.llmPageSize, pageToken = '' } = {}) {
      const params = new URLSearchParams();
      params.set('page_size', String(pageSize));
      const visibleKinds = this.currentLlmBackendEventKinds();
      if (visibleKinds.length === 0) params.append('event_kinds', '');
      for (const kind of visibleKinds) {
        params.append('event_kinds', kind);
      }
      if (executionId) params.set('execution_id', executionId);
      if (pageToken) params.set('page_token', pageToken);
      return `/projects/${this.selectedProjectId}/llm-events/cards?${params.toString()}`;
    },

    currentLlmVisibleEventKinds() {
      const projectKinds = this.llmVisibleKindsFromProject(this.project?.project || {});
      const visible = new Set(projectKinds);
      visible.delete('usage');
      return LLM_EVENT_KIND_OPTIONS.filter(kind => visible.has(kind));
    },

    currentLlmBackendEventKinds() {
      return llmBackendKindsForFilter(this.llmEventKindFilter, this.currentLlmVisibleEventKinds());
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

    async reloadLlmEventView() {
      if (!this.selectedProjectId || this.view !== 'graph' || !this.project?.project) return;
      await Promise.all([
        this.loadLatestLlmEvents(),
        this.loadLlmEventPage(this.llmPageToken),
      ]);
    },

    llmSelectedExecution() {
      const selectedId = this.selectedLlmExecutionIdForQuery();
      if (!selectedId) return null;
      return (this.llmExecutions || []).find(execution => execution.id === selectedId) || null;
    },

    async loadLatestLlmEvents() {
      if (!this.selectedProjectId || this.view !== 'graph' || !this.project?.project) return;
      const executionId = this.selectedLlmExecutionIdForQuery();
      const requestToken = ++this._llmLatestRequestToken;
      this.llmLatestLoading = true;
      try {
        const data = await this.api('GET', this.llmEventViewUrl({
          executionId,
          limit: this.llmLatestEventLimit,
          includeEventKinds: false,
        }));
        if (this._llmLatestRequestToken === requestToken
          && this.selectedLlmExecutionIdForQuery() === executionId) {
          const rows = Array.isArray(data?.primary_events) ? data.primary_events : [];
          const events = this.mergeLlmCommandEvents(this.filterLatestLlmPreviewRows(rows))
            .sort((a, b) => this.llmEventSequence(b) - this.llmEventSequence(a))
            .slice(0, 3);
          this.llmLatestEvents = events;
          this.applyLlmEventViewMeta(data);
          this._llmViewVersion++;
        }
      } catch (e) {
        console.error(e);
        if (this._llmLatestRequestToken === requestToken && this.selectedLlmExecutionIdForQuery() === executionId) {
          this.llmLatestEvents = [];
          this._llmViewVersion++;
        }
      } finally {
        if (this._llmLatestRequestToken === requestToken && this.selectedLlmExecutionIdForQuery() === executionId) {
          this.llmLatestLoading = false;
          this._llmViewVersion++;
        }
      }
    },

    estimateLlmPageSize() {
      const rawHeight = Number(this.$refs?.llmPagedEventList?.clientHeight || 0);
      const fallbackHeight = Math.max(0, (window.innerHeight || 720) - 355);
      const availableHeight = rawHeight > 0 ? rawHeight : fallbackHeight;
      const estimated = Math.floor(availableHeight / this.llmPageEstimatedCollapsedCardHeight);
      return Math.max(this.llmPageSizeMin, Math.min(this.llmPageSizeMax, estimated || this.llmPageSize));
    },

    refreshLlmPageSize() {
      const nextSize = this.estimateLlmPageSize();
      if (nextSize === this.llmPageSize) return false;
      this.llmPageSize = nextSize;
      this.llmPageToken = '';
      this.llmPageTokenHistory = [];
      this.llmPageNextToken = '';
      this.loadLlmEventPage('');
      return true;
    },

    onLlmLogViewportResize() {
      if (!this.selectedProjectId || this.view !== 'graph') return;
      clearTimeout(this._llmPageResizeTimer);
      this._llmPageResizeTimer = setTimeout(() => {
        this.refreshLlmPageSize();
      }, 120);
    },

    async resetLlmEventPagination() {
      this.llmPageToken = '';
      this.llmPageTokenHistory = [];
      this.llmPageNextToken = '';
      this.llmPagedEvents = [];
      this.llmPageHasNext = false;
      this.llmPageRangeLabel = '';
      this._llmViewVersion++;
      this.$nextTick(() => {
        const pageSizeReloading = this.refreshLlmPageSize();
        this.loadLatestLlmEvents();
        if (!pageSizeReloading) this.loadLlmEventPage('');
      });
    },

    async loadLlmEventPage(pageToken = this.llmPageToken) {
      if (!this.selectedProjectId || this.view !== 'graph' || !this.project?.project) return;
      const requestedPageToken = String(pageToken || '');
      const executionId = this.selectedLlmExecutionIdForQuery();
      const requestToken = ++this._llmPageRequestToken;
      this.llmPageLoading = true;
      this._llmViewVersion++;
      try {
        const data = await this.api('GET', this.llmEventCardsUrl({
          executionId,
          pageSize: this.llmPageSize,
          pageToken: requestedPageToken,
        }));
        if (this._llmPageRequestToken !== requestToken || this.selectedLlmExecutionIdForQuery() !== executionId) return;
        const cards = Array.isArray(data?.cards) ? data.cards : [];
        const events = cards
          .filter(event => this.isVisibleLlmEvent(event))
          .filter(event => this.matchesLlmEventKindFilter(event))
          .sort((a, b) => this.llmEventSequence(a) - this.llmEventSequence(b));
        this.llmPagedEvents = events;
        this.llmPageToken = requestedPageToken;
        this.llmPageNextToken = data?.next_page_token || '';
        this.llmPageHasNext = !!data?.has_next;
        this.llmPageRangeLabel = String(data?.page_range_label || '');
        const lastSequence = Number(data?.last_sequence || 0);
        if (Number.isFinite(lastSequence) && lastSequence > 0) {
          this.llmLastSequence = Math.max(this.llmLastSequence, lastSequence);
        }
        this.llmEvents = this.mergeLlmEventRows(this.llmEvents, [...events, ...this.llmLatestEvents], 1200);
        this._llmViewVersion++;
      } catch (e) {
        if (this._llmPageRequestToken === requestToken) console.error(e);
      } finally {
        if (this._llmPageRequestToken === requestToken && this.selectedLlmExecutionIdForQuery() === executionId) {
          this.llmPageLoading = false;
          this._llmViewVersion++;
        }
      }
    },

    nextLlmEventPage() {
      if (!this.llmPageHasNext || this.llmPageLoading) return;
      if (!this.llmPageNextToken) return;
      this.llmPageTokenHistory = [...this.llmPageTokenHistory, this.llmPageToken];
      this.loadLlmEventPage(this.llmPageNextToken);
    },

    previousLlmEventPage() {
      if (this.llmPageLoading || this.llmPageTokenHistory.length === 0) return;
      const stack = [...this.llmPageTokenHistory];
      const previousPageToken = stack.pop() || '';
      this.llmPageTokenHistory = stack;
      this.loadLlmEventPage(previousPageToken);
    },

    llmCanPollEvents(force = false) {
      if (force) return true;
      if (this.llmPollingPaused || this.replay.active) return false;
      return this.llmPanelVisible();
    },

    llmPanelVisible() {
      return this.view === 'graph' && !this.llmPanelCollapsed;
    },

    isFullLlmLogMode() {
      return false;
    },

    llmExecutionRefreshMs() {
      return this.llmPanelVisible() ? this.llmExecutionsRefreshMs : this.llmCollapsedExecutionsRefreshMs;
    },

    async pollLlmEvents(force = false) {
      if (!this.selectedProjectId || this.view !== 'graph' || !this.project?.project || this.replay.active) return;
      if (!this.llmCanPollEvents(force)) return;
      if (this.llmPollInFlight && !force) return;
      this.llmPollInFlight = true;
      try {
        this.llmPerfStats.incrementalPolls++;
        await this.loadLlmExecutions(force);
        await this.loadLatestLlmEvents();
      } catch (e) {
        console.error(e);
      } finally {
        this.llmLastEventPollAt = Date.now();
        this.llmPollInFlight = false;
      }
    },

    startLlmPolling() {
      if (this.llmPollTimer) return;
      this.llmPollTimer = setInterval(async () => {
        if (!this.selectedProjectId || this.view !== 'graph' || !this.project?.project) return;
        const now = Date.now();
        const canPollEvents = this.llmCanPollEvents(false);
        const executionRefreshMs = this.llmExecutionRefreshMs();
        if (now - this.llmExecutionsLastRefreshAt >= executionRefreshMs) {
          await this.loadLlmExecutions();
        }
        if (!canPollEvents) return;
        const hasRunning = this.llmExecutions.some(execution => this.llmExecutionIsRunning(execution));
        const pollMs = hasRunning ? this.llmFastPollMs : this.llmSlowPollMs;
        if (this.llmLatestEvents.length === 0 || now - this.llmLastEventPollAt >= pollMs) {
          await this.pollLlmEvents();
        }
      }, 1000);
    },

    filteredLlmEvents() {
      const cacheKey = `${this._llmViewVersion}:${this.llmSelectedExecutionId || ''}:${this.llmEventKindFilter}:${this.llmPagedEvents.length}`;
      if (this._llmViewCache && this._llmViewCacheKey === cacheKey) {
        return this._llmViewCache;
      }
      const startedAt = performance.now();
      const events = this.llmPagedEvents || [];
      const result = [...events].sort((a, b) => this.llmEventSequence(a) - this.llmEventSequence(b));
      this.recordLlmFilterPerf(performance.now() - startedAt, events.length);
      this._llmViewCache = result;
      this._llmViewCacheKey = cacheKey;
      return result;
    },

    initLlmPerfStats() {
      const paramsEnabled = new URLSearchParams(location.search || '').has('llmPerf');
      const storageEnabled = localStorage.getItem('cairn.debug.llmPerf') === '1';
      const hostEnabled = ['localhost', '127.0.0.1'].includes(location.hostname);
      this.llmPerfStats.enabled = hostEnabled && (paramsEnabled || storageEnabled);
      if (!this.llmPerfStats.enabled || this.llmPerfStats.observer || typeof PerformanceObserver === 'undefined') return;
      try {
        const observer = new PerformanceObserver((list) => {
          this.llmPerfStats.longTasks += list.getEntries().filter(entry => entry.duration >= 50).length;
          this.maybeLogLlmPerfStats();
        });
        observer.observe({ entryTypes: ['longtask'] });
        this.llmPerfStats.observer = observer;
      } catch (error) {
        this.llmPerfStats.enabled = false;
      }
    },

    recordLlmFilterPerf(durationMs, eventWindowSize) {
      if (!this.llmPerfStats.enabled) return;
      this.llmPerfStats.filteredCalls++;
      this.llmPerfStats.filteredMs += durationMs;
      this.llmPerfStats.lastEventWindowSize = eventWindowSize;
      this.maybeLogLlmPerfStats();
    },

    maybeLogLlmPerfStats(force = false) {
      if (!this.llmPerfStats.enabled) return;
      const now = Date.now();
      if (!force && now - this.llmPerfStats.lastLogAt < 10000) return;
      this.llmPerfStats.lastLogAt = now;
      const avgFilterMs = this.llmPerfStats.filteredCalls > 0
        ? (this.llmPerfStats.filteredMs / this.llmPerfStats.filteredCalls).toFixed(2)
        : '0.00';
      console.debug('[cairn:llm-perf]', {
        incrementalPolls: this.llmPerfStats.incrementalPolls,
        executionPolls: this.llmPerfStats.executionPolls,
        eventWindowSize: this.llmPerfStats.lastEventWindowSize,
        filteredCalls: this.llmPerfStats.filteredCalls,
        avgFilterMs,
        longTasks: this.llmPerfStats.longTasks,
      });
    },

    llmViewModel() {
      const cacheKey = `${this._llmViewVersion}:${this.llmSelectedExecutionId || ''}:${this.llmEventKindFilter}:${this.llmPagedEvents.length}:${this.llmPageLoading ? 1 : 0}:${this.llmPageRangeLabel}`;
      if (this._llmViewModelCache && this._llmViewModelCacheKey === cacheKey) {
        return this._llmViewModelCache;
      }
      const allEvents = this.filteredLlmEvents();
      const hasFilterHiddenEvents = !this.llmPageLoading && !this.llmPageToken && allEvents.length === 0 && !!this.llmHiddenEventSummary();
      const hiddenSummary = this.llmHiddenEventSummary();
      const model = {
        allEvents,
        events: allEvents,
        eventCount: allEvents.length,
        hiddenSummary,
        hasFilterHiddenEvents,
        showEmpty: allEvents.length === 0 && !hasFilterHiddenEvents && !this.llmPageLoading,
        canLoadMore: false,
      };
      this._llmViewModelCache = model;
      this._llmViewModelCacheKey = cacheKey;
      return model;
    },

    showMoreTimelineEvents() {
      this.timelineRenderLimit = Math.min(
        this.timelineEvents().length,
        this.timelineRenderLimit + this.timelineRenderStep,
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

    filterLatestLlmPreviewRows(events) {
      return (Array.isArray(events) ? events : [])
        .filter(event => event?.event_kind !== 'usage' && event?.event_kind !== 'system_event');
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
  };
}
