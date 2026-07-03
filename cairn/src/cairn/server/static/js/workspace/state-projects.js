import {
  defaultLlmVisibleEventKinds,
  defaultTaskAiProfileSelections,
  defaultTaskCapabilitiesMap,
  defaultTaskTimeouts,
} from '../shared/defaults.js';
import { sanitizeUserSkillIdsForProjectPayload } from '../shared/capability-selection.js';

export function createWorkspaceProjectsState() {
  return {
    projects: [],
    project: null,
    projectLoadError: '',
    selectedProjectId: '',
    projectPollInFlight: false,
    currentProjectPollState: null,
    isCreatingProject: false,
    newProjectPanel: 'basic',
    newProjectCatalog: {
      capabilities: [],
      roles: [],
      ai_profiles: [],
    },

    showNewProject: false,
    showIntentModal: false,
    showConcludeModal: false,
    showCompleteModal: false,
    showHintModal: false,
    showReopenModal: false,
    showRenameModal: false,
    showYamlModal: false,
    exportTab: 'yaml',
    exportProjectId: '',
    showDeleteModal: false,

    newProject: {
      title: '',
      origin: '',
      goal: '',
      hints: [{ content: '' }],
      attachments: [],
      role_id: '',
      capabilities: defaultTaskCapabilitiesMap(),
      ai_profiles: defaultTaskAiProfileSelections(),
      task_timeouts: defaultTaskTimeouts(),
      llm_visible_event_kinds: defaultLlmVisibleEventKinds(),
    },
    intentForm: { description: '' },
    concludeForm: { description: '', intentId: '' },
    completeForm: { description: '' },
    hintForm: { content: '' },
    reopenForm: { projectId: '', projectTitle: '', description: '' },
    renameForm: { projectId: '', originalTitle: '', title: '' },
    deleteConfirm: { id: '', title: '' },
    isDeletingProject: false,
    projectFiles: [],
    filesLoading: false,
    filesError: '',
    yamlPreviewTitle: '',
    yamlPreviewText: '',
    yamlPreviewHtml: '',
    projectListScrollTop: 0,
    shouldRestoreProjectListScroll: false,
    isStoppingAllProjects: false,
    invalidateProjectViewCaches() {
      this._timelineEventsCacheProject = null;
      this._timelineEventsCache = [];
      this._timelineViewModelCacheKey = '';
      this._timelineViewModelCache = null;
      this._summaryCardCache.clear();
      this._summaryCardCacheOrder = [];
    },

    projectFactCount(project = this.project) {
      if (!project) return 0;
      if (Number.isFinite(project.fact_count)) return project.fact_count;
      return Array.isArray(project.facts) ? project.facts.length : 0;
    },

    projectIntentCount(project = this.project) {
      if (!project) return 0;
      if (Number.isFinite(project.intent_count)) return project.intent_count;
      return Array.isArray(project.intents) ? project.intents.length : 0;
    },

    projectHintCount(project = this.project) {
      if (!project) return 0;
      if (Number.isFinite(project.hint_count)) return project.hint_count;
      return Array.isArray(project.hints) ? project.hints.length : 0;
    },

    applyProjectPollState(pollState) {
      if (!pollState) return;
      this.currentProjectPollState = pollState;
      const summary = this.projects.find(item => item.id === pollState.project_id);
      if (summary) {
        summary.title = pollState.title;
        summary.status = pollState.status;
        summary.reason = pollState.reason;
        summary.fact_count = pollState.fact_count;
        summary.intent_count = pollState.intent_count;
        summary.hint_count = pollState.hint_count;
      }
      if (this.project?.project?.id === pollState.project_id) {
        this.project.project.title = pollState.title;
        this.project.project.status = pollState.status;
        this.project.project.reason = pollState.reason;
        this.project.fact_count = pollState.fact_count;
        this.project.intent_count = pollState.intent_count;
        this.project.hint_count = pollState.hint_count;
      }
    },

    async loadProjectPollState(projectId = this.selectedProjectId) {
      if (!projectId) return null;
      const pollState = await this.api('GET', `/projects/${projectId}/poll-state`);
      this.applyProjectPollState(pollState);
      return pollState;
    },

    recentProjects() {
      const selected = this.projects.filter(p => p.id === this.selectedProjectId);
      const rest = this.projects.filter(p => p.id !== this.selectedProjectId);
      return [...selected, ...rest].slice(0, 12);
    },

    navigateProjects() {
      this.backToList(true);
      if (location.hash !== '#/') location.hash = '/';
      this.mobileNavOpen = false;
    },

    selectProjectSection(tab = 'detail') {
      if (!this.selectedProjectId) return;
      this.view = 'graph';
      this.graphMode = 'graph';
      this.switchSideTab(tab);
      this.mobileNavOpen = false;
      this.settleGraphViewport();
    },

    projectStatusBadgeClass(status) {
      const classes = {
        active: 'bg-teal-50 text-teal-600',
        stopped: 'bg-amber-50 text-amber-700',
        completed: 'bg-slate-100 text-slate-500',
      };
      return classes[status] || 'bg-slate-100 text-slate-500';
    },

    reasonBadgeText(reason, compact = false) {
      if (!reason) return '';
      if (compact) return `Reason · ${reason.worker}`;
      const trigger = reason.trigger ? ` (${reason.trigger})` : '';
      return `Reasoning · ${reason.worker}${trigger}`;
    },

    workingIntentBadgeText(count) {
      return `Exploring · ${count}`;
    },

    isBootstrapIntent(intent) {
      return Boolean(
        intent
        && intent.description === 'bootstrap'
        && intent.creator === 'dispatcher.bootstrap'
        && Array.isArray(intent.from)
        && intent.from.length === 1
        && intent.from[0] === 'origin'
        && intent.to === null,
      );
    },

    projectIsActive() {
      return !this.replay.active && this.project?.project?.status === 'active';
    },

    countProjectsByStatus(status) {
      return this.projects.filter(project => project.status === status).length;
    },

    hasActiveProjects() {
      return this.projects.some(project => project.status === 'active');
    },

    projectCanWriteHints() {
      return !this.replay.active && ['active', 'stopped', 'completed'].includes(this.project?.project?.status);
    },

    async loadProjects() {
      try { this.projects = await this.api('GET', '/projects'); } catch(e) { console.error(e); }
    },

    rememberProjectListScroll() {
      const scroller = this.$refs.projectListScroll;
      if (!scroller) return;
      this.projectListScrollTop = scroller.scrollTop;
    },

    restoreProjectListScroll() {
      if (!this.shouldRestoreProjectListScroll) return;
      this.$nextTick(() => {
        const scroller = this.$refs.projectListScroll;
        if (!scroller) return;
        const maxScrollTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
        scroller.scrollTop = Math.min(this.projectListScrollTop, maxScrollTop);
        this.shouldRestoreProjectListScroll = false;
      });
    },

    highlightYamlScalar(value) {
      const escaped = this.escapeHtml(value);
      if (!value.trim()) return escaped;
      if (/^\s*#.*$/.test(value)) return `<span style="color:#64748b">${escaped}</span>`;
      if (/^\s*['"].*['"]\s*$/.test(value)) return `<span style="color:#15803d">${escaped}</span>`;
      if (/^\s*\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2})\s*$/.test(value)) return `<span style="color:#b45309">${escaped}</span>`;
      if (/^\s*(true|false|null|~)\s*$/i.test(value)) return `<span style="color:#b91c1c">${escaped}</span>`;
      if (/^\s*-?\d+(\.\d+)?\s*$/.test(value)) return `<span style="color:#0f766e">${escaped}</span>`;
      if (/^\s*(origin|goal|f\d+|i\d+)\s*$/i.test(value)) return `<span style="color:#6d28d9">${escaped}</span>`;
      return `<span style="color:#0f172a">${escaped}</span>`;
    },

    highlightYamlLine(line) {
      if (/^\s*$/.test(line)) return '';
      if (/^\s*#/.test(line)) return `<span style="color:#64748b">${this.escapeHtml(line)}</span>`;

      const listKeyMatch = line.match(/^(\s*-\s+)([^:#\n][^:]*):(.*)$/);
      if (listKeyMatch) {
        const [, prefix, key, rest] = listKeyMatch;
        return `${this.escapeHtml(prefix)}<span style="color:#7dd3fc">${this.escapeHtml(key)}</span>:${this.highlightYamlScalar(rest)}`;
      }

      const keyMatch = line.match(/^(\s*)([^:#\n][^:]*):(.*)$/);
      if (keyMatch) {
        const [, indent, key, rest] = keyMatch;
        return `${this.escapeHtml(indent)}<span style="color:#7dd3fc">${this.escapeHtml(key)}</span>:${this.highlightYamlScalar(rest)}`;
      }

      const listValueMatch = line.match(/^(\s*-\s+)(.*)$/);
      if (listValueMatch) {
        const [, prefix, rest] = listValueMatch;
        return `${this.escapeHtml(prefix)}${this.highlightYamlScalar(rest)}`;
      }

      return this.highlightYamlScalar(line);
    },

    yamlSectionTint(sectionName) {
      const tints = {
        project: { header: '#eff6ff', body: '#fafcff', itemA: '#f3f8ff', itemB: '#edf5ff' },
        hints: { header: '#fffbeb', body: '#fffef8', itemA: '#fffaf0', itemB: '#fff6e8' },
        facts: { header: '#eef2ff', body: '#fafaff', itemA: '#f5f7ff', itemB: '#eef3ff' },
        intents: { header: '#ecfdf5', body: '#f8fdfb', itemA: '#f1fbf5', itemB: '#eaf8ef' },
      };
      return tints[sectionName] || { header: '#f8fafc', body: '#ffffff', itemA: '#f8fafc', itemB: '#f1f5f9' };
    },

    async copyYamlPreview() {
      if (!this.yamlPreviewText) return;
      try {
        await this.copyText(this.yamlPreviewText);
        this.showToast('Copied');
      } catch {
        this.showToast('Copy failed', 'error');
      }
    },

    highlightYaml(text) {
      const lines = String(text ?? '').split('\n');
      let currentSection = '';
      let activeItemIndent = null;
      let activeItemStripe = 0;
      let nextItemStripe = 0;

      return lines.map((line) => {
        const topLevelMatch = line.match(/^([A-Za-z_][A-Za-z0-9_-]*):\s*$/);
        if (topLevelMatch) {
          currentSection = topLevelMatch[1];
          activeItemIndent = null;
          activeItemStripe = 0;
          nextItemStripe = 0;
        }

        const tint = this.yamlSectionTint(currentSection);
        const indent = (line.match(/^(\s*)/) || ['',''])[1].length;
        const isBlank = /^\s*$/.test(line);
        const isListItem = /^(\s*)-\s+/.test(line);
        const isTopLevelItem = isListItem && indent === 0;

        if (isTopLevelItem) {
          activeItemIndent = indent;
          activeItemStripe = nextItemStripe;
          nextItemStripe = nextItemStripe === 0 ? 1 : 0;
        } else if (!isBlank && activeItemIndent !== null && indent === 0) {
          activeItemIndent = null;
        }

        const isNestedListItem = isListItem && activeItemIndent !== null && indent > activeItemIndent;
        const isItemContinuation = !isListItem && !isBlank && activeItemIndent !== null && indent > activeItemIndent;
        const isBlankWithinItem = isBlank && activeItemIndent !== null;
        const isItemLine = isTopLevelItem || isNestedListItem || isItemContinuation || isBlankWithinItem;
        const lineHtml = isBlank ? '&nbsp;' : this.highlightYamlLine(line);
        let background = currentSection ? tint.body : 'transparent';
        let fontWeight = '400';

        if (topLevelMatch) {
          background = tint.header;
          fontWeight = '700';
        } else if (isItemLine) {
          background = activeItemStripe === 0 ? tint.itemA : tint.itemB;
        }

        return `<div style="white-space:pre;padding:0 16px;background:${background};font-weight:${fontWeight};color:#0f172a">${lineHtml}</div>`;
      }).join('');
    },

    safeExportPreviewHtml(tab, text) {
      return tab === 'yaml' ? this.highlightYaml(text) : this.highlightTimeline(text);
    },

    projectLabel(projectId, projectTitle) {
      return projectTitle ? `${projectId} - ${projectTitle}` : projectId;
    },

    deleteConfirmLabel() {
      return this.projectLabel(this.deleteConfirm.id, this.deleteConfirm.title);
    },

    requestDeleteProject(projectId, projectTitle = '') {
      if (!projectId) return;
      this.deleteConfirm = { id: projectId, title: projectTitle };
      this.showDeleteModal = true;
    },

    closeDeleteModal(force = false) {
      if (this.isDeletingProject && !force) return;
      this.showDeleteModal = false;
      this.deleteConfirm = { id: '', title: '' };
    },

    async viewProjectYaml(projectId, projectTitle = '') {
      if (!projectId) return;
      this.exportProjectId = projectId;
      this.yamlPreviewTitle = this.projectLabel(projectId, projectTitle);
      this.exportTab = 'yaml';
      await this.loadExportTab('yaml');
      this.showYamlModal = true;
    },

    async switchExportTab(tab) {
      if (tab === this.exportTab) return;
      this.exportTab = tab;
      await this.loadExportTab(tab);
    },

    async loadExportTab(tab) {
      if (!this.exportProjectId) return;
      try {
        const text = await this.fetchText(`/projects/${this.exportProjectId}/export?format=${tab}`);
        this.yamlPreviewText = text;
        this.yamlPreviewHtml = this.safeExportPreviewHtml(tab, text);
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    deleteProject() {
      if (!this.selectedProjectId) return;
      this.requestDeleteProject(this.selectedProjectId, this.project?.project?.title || '');
    },

    deleteProjectById(projectId, projectTitle = '') {
      this.requestDeleteProject(projectId, projectTitle);
    },

    async confirmDeleteProject() {
      const projectId = this.deleteConfirm.id;
      if (!projectId || this.isDeletingProject) return;
      try {
        this.isDeletingProject = true;
        await this.api('DELETE', `/projects/${projectId}`);
        this.closeDeleteModal(true);
        if (this.selectedProjectId === projectId && this.view === 'graph') {
          this.resetLlmState();
          this.backToList();
        } else {
          await this.loadProjects();
        }
        this.showToast(`Deleted ${projectId}`);
      } catch (e) {
        this.showToast(e.message, 'error');
      } finally {
        this.isDeletingProject = false;
        if (!this.showDeleteModal) this.deleteConfirm = { id: '', title: '' };
      }
    },

    async loadProject(id, options = {}) {
      const { invalidateCaches = true } = options;
      try {
        this.projectLoadError = '';
        const nextProject = await this.api('GET', `/projects/${id}`);
        nextProject.fact_count = Array.isArray(nextProject.facts) ? nextProject.facts.length : 0;
        nextProject.intent_count = Array.isArray(nextProject.intents) ? nextProject.intents.length : 0;
        nextProject.hint_count = Array.isArray(nextProject.hints) ? nextProject.hints.length : 0;
        this.project = nextProject;
        if (invalidateCaches) this.invalidateProjectViewCaches();
        this.currentProjectPollState = {
          project_id: nextProject.project.id,
          title: nextProject.project.title,
          status: nextProject.project.status,
          reason: nextProject.project.reason,
          fact_count: nextProject.fact_count,
          intent_count: nextProject.intent_count,
          hint_count: nextProject.hint_count,
          graph_revision: this.currentProjectPollState?.project_id === nextProject.project.id ? this.currentProjectPollState.graph_revision : 0,
          timeline_revision: this.currentProjectPollState?.project_id === nextProject.project.id ? this.currentProjectPollState.timeline_revision : 0,
        };
        if (this.sideTab === 'files' && this.selectedProjectId === id) await this.loadProjectFiles(true);
        return true;
      } catch(e) {
        this.project = null;
        this.currentProjectPollState = null;
        this.projectLoadError = e.message || 'Project not found';
        this.invalidateProjectViewCaches();
        this.showToast(this.projectLoadError, 'error');
        return false;
      }
    },

    async loadProjectFiles(force = false) {
      if (!this.selectedProjectId) return;
      if (!force && this.projectFiles.length > 0) return;
      try {
        this.filesLoading = true;
        this.filesError = '';
        const data = await this.api('GET', `/projects/${this.selectedProjectId}/files`);
        this.projectFiles = data.files || [];
      } catch (e) {
        this.filesError = e.message;
        this.projectFiles = [];
      } finally {
        this.filesLoading = false;
      }
    },

    viewProjectFiles() {
      this.switchSideTab('files');
    },

    hasProjectFileRefs(text) {
      return /\/home\/kali\/workspace\/(project|attachments)\//.test(String(text || ''));
    },

    projectFileGroups() {
      const labels = {
        reports: 'Reports',
        exploit: 'Exploit / PoC',
        attachments: 'Attachments',
        other: 'Other project files',
      };
      return ['reports', 'exploit', 'attachments', 'other'].map(id => ({
        id,
        label: labels[id],
        files: this.projectFiles.filter(file => file.category === id),
      }));
    },

    projectFileDisplayPath(file) {
      const root = file.source === 'attachment'
        ? `/home/kali/workspace/attachments/${this.selectedProjectId}`
        : '/home/kali/workspace';
      return `${root}/${file.path}`;
    },

    projectFileDownloadUrl(file) {
      return `/projects/${encodeURIComponent(this.selectedProjectId)}/files/download?source=${encodeURIComponent(file.source)}&path=${encodeURIComponent(file.path)}`;
    },

    async downloadProjectFile(file) {
      try {
        const r = await this.authFetch(this.projectFileDownloadUrl(file), { method: 'GET' });
        if (!r.ok) {
          if (r.status === 401) this.showLogin = true;
          const text = await r.text().catch(() => '');
          let msg = `HTTP ${r.status}`;
          try {
            const data = JSON.parse(text);
            if (typeof data.detail === 'string') msg = data.detail;
            else if (Array.isArray(data.detail)) msg = data.detail.map(e => e.msg).join('; ');
          } catch (e) {
            if (text) msg = text;
          }
          throw new Error(msg);
        }
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = this.filenameFromContentDisposition(r.headers.get('content-disposition')) || file.name || 'download';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      } catch (e) {
        this.filesError = e.message || String(e);
      }
    },

    resetProjectFiles() {
      this.projectFiles = [];
      this.filesLoading = false;
      this.filesError = '';
    },

    resetNewProject() {
      this.newProject = {
        title: '',
        origin: '',
        goal: '',
        hints: [{ content: '' }],
        attachments: [],
        role_id: '',
        capabilities: this.defaultTaskCapabilitiesMap(),
        ai_profiles: this.defaultTaskAiProfileSelections(),
        task_timeouts: this.defaultTaskTimeouts(),
        llm_visible_event_kinds: this.defaultLlmVisibleEventKinds(),
      };
      this.newProjectCapabilityPanel = 'bootstrap';
    },

    handleNewProjectAttachmentFiles(event) {
      const files = Array.from(event.target.files || []);
      if (files.length === 0) return;
      const stamp = Date.now();
      const offset = this.newProject.attachments.length;
      const attachments = files.map((file, idx) => ({
        file,
        description: '',
        key: `${stamp}-${offset + idx}-${file.name}-${file.size}-${file.lastModified}`,
      }));
      this.newProject.attachments = [...this.newProject.attachments, ...attachments];
      event.target.value = '';
    },

    async uploadProjectAttachments(projectId, attachments, actor) {
      if (!attachments || attachments.length === 0) return null;
      const form = new FormData();
      for (const attachment of attachments) {
        form.append('files', attachment.file, attachment.file.name);
        form.append('descriptions', attachment.description?.trim() || '附件');
      }
      form.append('creator', actor);
      const r = await this.authFetch(`/projects/${encodeURIComponent(projectId)}/attachments`, { method: 'POST', body: form });
      let data = null;
      try { data = await r.json(); } catch {}
      if (!r.ok) {
        let msg = `HTTP ${r.status}`;
        if (typeof data?.detail === 'string') msg = data.detail;
        else if (Array.isArray(data?.detail)) msg = data.detail.map(e => e.msg).join('; ');
        throw new Error(msg);
      }
      return data;
    },

    async openNewProject() {
      this.resetNewProject();
      this.newProjectPanel = 'basic';
      this.newProjectCapabilityPanel = 'bootstrap';
      this.view = 'newProject';
      this.showNewProject = false;
      this.mobileNavOpen = false;
      await Promise.all([this.loadNewProjectCatalog(), this.loadAiProfiles()]);
      this.ensureAllTaskAiProfilesSelected(this.newProject, this.newProjectAiProfileItems());
    },

    cancelNewProject() {
      if (this.isCreatingProject) return;
      this.showNewProject = false;
      this.resetNewProject();
      this.navigateProjects();
    },

    async loadNewProjectCatalog() {
      try {
        const [capabilities, roles, aiProfiles, taskTimeouts] = await Promise.all([
          this.api('GET', '/capabilities/catalog'),
          this.api('GET', '/roles/catalog'),
          this.api('GET', '/ai-profiles'),
          this.api('GET', '/task-timeouts/defaults'),
        ]);
        this.aiProfiles = aiProfiles || [];
        this.newProject.task_timeouts = this.normalizeTaskTimeouts(taskTimeouts);
        this.newProjectCatalog = {
          capabilities: capabilities || [],
          roles: roles || [],
          ai_profiles: this.aiProfiles,
        };
      } catch (e) {
        console.error(e);
        this.newProjectCatalog = { capabilities: [], roles: [], ai_profiles: [] };
        this.showToast(`Catalog load failed: ${e.message}`, 'error');
      }
    },

    newProjectRoleItems() {
      return (this.newProjectCatalog.roles || []).filter(item => item.available !== false);
    },

    sanitizeUserSkillIdsForProjectPayload(ids) {
      return sanitizeUserSkillIdsForProjectPayload(ids, this.roleDefaultTopLevelSkillIds());
    },

    newProjectAiSelectionSummary() {
      const selections = this.ensureTaskAiProfileSelections(this.newProject);
      const parts = this.aiProfileTaskTypes().map(task => {
        const profile = this.newProjectAiProfileItems().find(item => item.id === selections[task.key]?.primary_profile_id);
        const model = selections[task.key]?.primary_model || '';
        const reasoning = selections[task.key]?.primary_reasoning_type || '';
        return `${task.label}: ${profile ? `${profile.name} / ${model}${reasoning ? ' / ' + reasoning : ''}` : 'missing profile'}`;
      });
      return parts.join(' · ');
    },

    projectModalPanels() {
      return [
        { key: 'basic', label: 'Basic' },
        { key: 'capabilities', label: 'Capabilities' },
        { key: 'ai', label: 'AI Worker Chains' },
      ];
    },

    async toggleProjectStop() {
      if (!this.selectedProjectId || !this.project || this.project.project.status === 'completed') return;
      const nextStatus = this.project.project.status === 'active' ? 'stopped' : 'active';
      try {
        await this.setProjectStatus(this.selectedProjectId, nextStatus);
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async toggleProjectStopById(projectId, currentStatus) {
      if (!projectId || currentStatus === 'completed') return;
      const nextStatus = currentStatus === 'active' ? 'stopped' : 'active';
      try {
        await this.setProjectStatus(projectId, nextStatus);
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async setProjectStatus(projectId, status, options = {}) {
      const { reload = true, toast = true } = options;
      const updated = await this.api('PUT', `/projects/${projectId}/status`, { status });
      const projectSummary = this.projects.find(item => item.id === projectId);
      if (projectSummary) {
        projectSummary.status = updated.status;
        projectSummary.reason = updated.reason;
      }
      if (this.selectedProjectId === projectId && this.project) {
        this.project.project.status = updated.status;
        this.project.project.reason = updated.reason;
        if (!this.projectIsActive()) {
          this.showIntentModal = false;
          this.showConcludeModal = false;
          this.showCompleteModal = false;
        }
        if (!this.projectCanWriteHints()) {
          this.showHintModal = false;
        }
      }
      if (reload) await this.loadProjects();
      if (toast) this.showToast(status === 'stopped' ? 'Project stopped' : 'Project resumed');
      return updated;
    },

    async stopAllActiveProjects() {
      const activeProjects = this.projects.filter(project => project.status === 'active');
      if (activeProjects.length === 0 || this.isStoppingAllProjects) return;
      this.isStoppingAllProjects = true;
      try {
        const results = await Promise.allSettled(
          activeProjects.map(project => this.setProjectStatus(project.id, 'stopped', { reload: false, toast: false }))
        );
        await this.loadProjects();
        const successCount = results.filter(result => result.status === 'fulfilled').length;
        const failureCount = results.length - successCount;
        if (failureCount === 0) {
          this.showToast(`Stopped ${successCount} active project${successCount === 1 ? '' : 's'}`);
        } else {
          this.showToast(`Stopped ${successCount} projects, ${failureCount} failed`, 'error');
        }
      } catch (e) {
        this.showToast(e.message, 'error');
      } finally {
        this.isStoppingAllProjects = false;
      }
    },

    openReopenProject(projectId, projectTitle = '') {
      if (!projectId) return;
      this.reopenForm = { projectId, projectTitle, description: '' };
      this.showReopenModal = true;
    },

    openRenameProject(projectId, projectTitle = '') {
      if (!projectId) return;
      this.renameForm = { projectId, originalTitle: projectTitle, title: projectTitle };
      this.showRenameModal = true;
      this.$nextTick(() => {
        this.$refs.renameTitleInput?.focus();
        this.$refs.renameTitleInput?.select?.();
      });
    },

    async renameProject() {
      const projectId = this.renameForm.projectId || this.selectedProjectId;
      if (!projectId) return;
      try {
        const updated = await this.api('PUT', `/projects/${projectId}/title`, {
          title: this.renameForm.title,
        });
        const projectSummary = this.projects.find(item => item.id === projectId);
        if (projectSummary) {
          projectSummary.title = updated.title;
        }
        if (this.selectedProjectId === projectId && this.project) {
          this.project.project.title = updated.title;
        }
        this.showRenameModal = false;
        this.renameForm = { projectId: '', originalTitle: '', title: '' };
        await this.loadProjects();
        this.showToast('Project renamed');
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async reopenProject() {
      const projectId = this.reopenForm.projectId || this.selectedProjectId;
      if (!projectId) return;
      try {
        const actor = this.actorName();
        await this.api('POST', `/projects/${projectId}/reopen`, {
          description: this.reopenForm.description,
          creator: actor,
        });
        this.showReopenModal = false;
        this.reopenForm = { projectId: '', projectTitle: '', description: '' };
        await this.loadProjects();
        if (this.selectedProjectId === projectId && this.view === 'graph') {
          await this.loadProject(projectId);
          this.updateGraph();
        }
        this.showToast('Project reopened');
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async openProject(id) {
      if (this.replay.active) {
        this.stopReplayTimer();
        this.replay.active = false;
        this.replay.playing = false;
        this.replay.frames = [];
        this.replay.visibleEvents = [];
        this.replay.frameIndex = -1;
        this.replay.sourceProject = null;
        this.invalidateProjectViewCaches();
        this.polling = true;
      }
      this.rememberProjectListScroll();
      this.resetLlmState();
      this.selectedProjectId = id;
      this.currentProjectPollState = null;
      this.selectedNode = null;
      this.selectedFacts = [];
      this.selectedTimelineEntryId = null;
      this.showReplayConfigModal = false;
      this.resetReplayConfig();
      this.resetProjectFiles();
      const loaded = await this.loadProject(id);
      this.view = 'graph';
      this.graphMode = 'graph';
      this.llmPanelCollapsed = false;
      if (!loaded) {
        this.capabilities = {
          catalog: [],
          tasks: this.defaultTaskCapabilitiesMap(),
          health: {},
          unavailable: { mcp_server_ids: [], skill_ids: [] },
          projectAiProfiles: { catalog: [], selections: this.defaultTaskAiProfileSelections(), snapshots: [], unavailable_profile_ids: [] },
        };
        this.resetLlmState();
        this.teardownAutoFit();
        if (this.cy) { this.cy.destroy(); this.cy = null; }
        if (location.hash !== `#/projects/${id}`) location.hash = `/projects/${id}`;
        return;
      }
      await this.loadProjectPollState(id);
      await this.loadCapabilities();
      await this.loadLlmExecutions(true);
      await this.pollLlmEvents(true);
      if (location.hash !== `#/projects/${id}`) location.hash = `/projects/${id}`;
      this.$nextTick(() => {
        this.resetLlmEventPagination();
        const clampedWidth = this.clampPanelWidth(this.sidePanelWidth);
        if (clampedWidth !== this.sidePanelWidth) {
          this.sidePanelWidth = clampedWidth;
          this.saveSidePanelWidth();
        }
        const clampedLlmWidth = this.clampLlmPanelWidth(this.llmPanelWidth);
        if (clampedLlmWidth !== this.llmPanelWidth) {
          this.llmPanelWidth = clampedLlmWidth;
          this.saveLlmPanelPrefs();
        }
        this.teardownAutoFit();
        if (this.cy) { this.cy.destroy(); this.cy = null; }
        void this.initGraph();
      });
    },

    backToList(fromRoute) {
      if (this.replay.active) {
        this.stopReplayTimer();
        this.replay.active = false;
        this.replay.playing = false;
        this.replay.frames = [];
        this.replay.visibleEvents = [];
        this.replay.frameIndex = -1;
        this.replay.sourceProject = null;
        this.invalidateProjectViewCaches();
        this.polling = true;
      }
      this.view = 'list';
      this.shouldRestoreProjectListScroll = true;
      this.project = null;
      this.currentProjectPollState = null;
      this.invalidateProjectViewCaches();
      this.selectedProjectId = '';
      this.resetLlmState();
      this.selectedNode = null;
      this.selectedFacts = [];
      this.selectedTimelineEntryId = null;
      this.showReplayConfigModal = false;
      this.resetReplayConfig();
      this.resetProjectFiles();
      this.teardownAutoFit();
      if (this.cy) { this.cy.destroy(); this.cy = null; }
      if (!fromRoute) location.hash = '/';
      this.loadProjects().then(() => this.restoreProjectListScroll());
    },

    intentDisplayTitle(intent) {
      return intent?.id || '';
    },

    intentDisplaySubtitle(intent) {
      if (!intent) return 'From: — · To: —';
      const fromLabel = Array.isArray(intent.from) && intent.from.length > 0
        ? intent.from.join(' ')
        : '—';
      const toLabel = intent.to || '—';
      return `From: ${fromLabel} · To: ${toLabel}`;
    },

    selectedReleasableOpenIntentRecord() {
      const intent = this.selectedOpenIntentRecord();
      if (!intent?.worker) return null;
      return intent.worker === this.actorName() ? intent : null;
    },

    intentDotClass(i) {
      if (i.to) return 'bg-teal-400';
      if (this.isBootstrapIntent(i)) return i.worker ? 'bg-orange-400' : 'bg-orange-200';
      return i.worker ? 'bg-amber-400' : 'bg-slate-300';
    },
    intentStatusClass(i) {
      if (i.to) return 'text-teal-600';
      if (this.isBootstrapIntent(i)) return i.worker ? 'text-orange-600' : 'text-orange-400';
      return i.worker ? 'text-amber-600' : 'text-slate-400';
    },
    intentStatusLabel(i) {
      if (i.to) return 'Concluded';
      if (this.isBootstrapIntent(i)) return i.worker ? 'Bootstrap Running' : 'Bootstrap Pending';
      return i.worker ? 'In Progress' : 'Unclaimed';
    },

    canCreateProject() {
      return !this.isCreatingProject
        && !!this.newProject.title
        && !!this.newProject.origin
        && !!this.newProject.goal
        && this.taskTimeoutsComplete(this.newProject.task_timeouts)
        && this.taskAiProfileSelectionsComplete(this.newProject, this.newProjectAiProfileItems());
    },

    async createProject() {
      if (this.isCreatingProject) return;
      let createdProjectId = null;
      try {
        if (!this.taskAiProfileSelectionsComplete(this.newProject, this.newProjectAiProfileItems())) {
          throw new Error('Select an AI Profile for Bootstrap, Intent, and Reason before creating a project.');
        }
        if (!this.taskTimeoutsComplete(this.newProject.task_timeouts)) {
          throw new Error('Set all task timeouts to positive seconds before creating the project.');
        }
        this.isCreatingProject = true;
        const actor = this.actorName();
        const attachments = [...(this.newProject.attachments || [])];
        const hintContents = this.newProject.hints.filter(h => h.content?.trim());
        const body = { title: this.newProject.title, origin: this.newProject.origin, goal: this.newProject.goal };
        const hints = hintContents.map(h => ({ content: h.content.trim(), creator: actor }));
        if (hints.length > 0) body.hints = hints;
        body.capabilities = this.capabilitiesForNewProject();
        if (this.newProject.role_id) {
          body.role_id = this.newProject.role_id;
        }
        const aiSelections = this.ensureTaskAiProfileSelections(this.newProject);
        body.ai_profiles = this.compactTaskAiProfileSelections(aiSelections);
        body.task_timeouts = this.taskTimeoutsForPayload(this.newProject.task_timeouts);
        body.llm_visible_event_kinds = this.newProject.llm_visible_event_kinds || this.defaultLlmVisibleEventKinds();
        const data = await this.api('POST', '/projects', body);
        createdProjectId = data.project.id;
        await this.uploadProjectAttachments(createdProjectId, attachments, actor);
        this.resetNewProject();
        await this.loadProjects();
        await this.openProject(createdProjectId);
        this.showToast(attachments.length > 0 ? `Project created with ${attachments.length} attachment${attachments.length === 1 ? '' : 's'}` : 'Project created');
      } catch(e) {
        if (createdProjectId) {
          await this.loadProjects();
          await this.openProject(createdProjectId);
          this.showToast(`Project created, but attachment upload failed: ${e.message}`, 'error');
        } else {
          this.showToast(e.message, 'error');
        }
      } finally {
        this.isCreatingProject = false;
      }
    },

    openCreateIntent() {
      if (!this.canActOnSelectedFacts()) return;
      this.intentForm = { description:'' };
      this.showIntentModal = true;
    },

    async createIntent(claim = false) {
      try {
        const actor = this.actorName();
        await this.api('POST', `/projects/${this.selectedProjectId}/intents`, {
          from: this.selectedFacts,
          description: this.intentForm.description,
          creator: actor,
          worker: claim ? actor : null,
        });
        this.showIntentModal = false;
        await this.loadProject(this.selectedProjectId);
        this.updateGraph();
        this.showToast(claim ? 'Intent declared and claimed' : 'Intent declared');
      } catch(e) { this.showToast(e.message, 'error'); }
    },

    async sendHeartbeatForSelectedIntent() {
      const intent = this.selectedActionableOpenIntentRecord();
      if (!intent) return;
      try {
        const actor = this.actorName();
        const claiming = !intent.worker;
        await this.api('POST', `/projects/${this.selectedProjectId}/intents/${intent.id}/heartbeat`, { worker: actor });
        await this.loadProject(this.selectedProjectId);
        this.updateGraph();
        this.showToast(claiming ? 'Intent claimed' : 'Heartbeat sent');
      } catch(e) { this.showToast(e.message, 'error'); }
    },

    async releaseSelectedIntent() {
      const intent = this.selectedReleasableOpenIntentRecord();
      if (!intent) return;
      try {
        const actor = this.actorName();
        await this.api('POST', `/projects/${this.selectedProjectId}/intents/${intent.id}/release`, { worker: actor });
        await this.loadProject(this.selectedProjectId);
        this.updateGraph();
        this.showToast('Intent released');
      } catch(e) { this.showToast(e.message, 'error'); }
    },

    openConclude(intent) { this.concludeForm = { description:'', intentId: intent.id }; this.showConcludeModal = true; },

    async concludeIntent() {
      try {
        const actor = this.actorName();
        await this.api('POST', `/projects/${this.selectedProjectId}/intents/${this.concludeForm.intentId}/conclude`, { worker: actor, description: this.concludeForm.description });
        this.showConcludeModal = false;
        this.selectedNode = null;
        await this.loadProject(this.selectedProjectId);
        this.updateGraph();
        this.showToast('Intent concluded');
      } catch(e) { this.showToast(e.message, 'error'); }
    },

    openCompleteProject() {
      if (!this.canActOnSelectedFacts()) return;
      this.completeForm = { description:'' };
      this.showCompleteModal = true;
    },

    openHintModal() {
      if (!this.projectCanWriteHints()) return;
      this.hintForm = { content:'' };
      this.showHintModal = true;
    },

    async completeProject() {
      try {
        const actor = this.actorName();
        await this.api('POST', `/projects/${this.selectedProjectId}/complete`, { from: this.selectedFacts, description: this.completeForm.description, worker: actor });
        this.showCompleteModal = false;
        await this.loadProjects();
        await this.loadProject(this.selectedProjectId);
        this.updateGraph();
        this.showToast('Project completed');
      } catch(e) { this.showToast(e.message, 'error'); }
    },

    async addHint() {
      if (!this.projectCanWriteHints()) return;
      try {
        const actor = this.actorName();
        await this.api('POST', `/projects/${this.selectedProjectId}/hints`, { content: this.hintForm.content, creator: actor });
        this.showHintModal = false;
        this.hintForm = { content:'' };
        await this.loadProjects();
        await this.loadProject(this.selectedProjectId);
        this.sideTab = 'hints';
        this.showToast('Hint added');
      } catch(e) { this.showToast(e.message, 'error'); }
    },

  };
}
