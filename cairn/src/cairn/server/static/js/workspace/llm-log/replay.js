export function createWorkspaceLogReplayState() {
  return {
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
  };
}
