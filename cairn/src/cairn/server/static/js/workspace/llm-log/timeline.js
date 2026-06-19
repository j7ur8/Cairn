export function createWorkspaceLogTimelineState() {
  return {
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
        this.timelineRenderLimit,
      ].join('|');
      if (this._timelineViewModelCache && this._timelineViewModelCacheKey === cacheKey) {
        return this._timelineViewModelCache;
      }
      const latestEntryId = events.length > 0 ? events[events.length - 1].id : null;
      const visibleEvents = events.slice(-this.timelineRenderLimit);
      const model = {
        events: visibleEvents,
        empty: events.length === 0,
        latestEntryId,
        hiddenCount: Math.max(0, events.length - visibleEvents.length),
        canLoadMore: events.length > visibleEvents.length,
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
}
