window.CairnParts = window.CairnParts || {};
CairnParts.core = function () {
  return {
    task_type_specs: [],
    task_types: [],
    view: 'list',
    polling: true,
    pollTimer: null,
    proxies: [],
    showLogin: false,
    currentUser: null,
    loginForm: { email: '', password: '', error: '', busy: false },
    appBootstrapped: false,
    _summaryCardCache: new Map(),
    _summaryCardCacheOrder: [],
    _loadedScriptUrls: new Set(['/static/vendor/dagre.min.js', '/static/vendor/cytoscape.min.js', '/static/vendor/cytoscape-dagre.js']),
    _scriptLoadPromises: {},
    _centerAnimation: null,
    _hashChangeHandler: null,
    async init() {
      this._panelResizeMove = (e) => this.onPanelResize(e);
      this._panelResizeStop = () => this.stopPanelResize();
      this._llmPanelResizeMove = (e) => this.onLlmPanelResize(e);
      this._llmPanelResizeStop = () => this.stopLlmPanelResize();
      window.addEventListener('pointermove', this._panelResizeMove);
      window.addEventListener('pointerup', this._panelResizeStop);
      window.addEventListener('pointermove', this._llmPanelResizeMove);
      window.addEventListener('pointerup', this._llmPanelResizeStop);
      // Invalidate the LLM-event view cache whenever any input changes. This
      // lets filteredLlmEvents() / _llmEventsForView() reuse a single
      // computation across the 6+ template call sites in a render. Manual
      // bumps at pollLlmEvents / loadLlmExecutionEvents / resetLlmState are
      // belt-and-suspenders for the push/slice mutation paths.
      const bumpLlmView = () => { this._llmViewVersion++; };
      this.$watch('llmEvents', bumpLlmView);
      this.$watch('llmSelectedExecutionId', bumpLlmView);
      this.$watch('llmSelectedExecutionEvents', bumpLlmView);
      this.$watch('llmEventKindFilter', bumpLlmView);
      this.$watch('_llmViewVersion', () => {
        this.llmRenderLimit = 100;
      });
      this.loadLocalPrefs();
      // Validate the stored token (if any) before loading any data
      // so the first GET /projects does not pop a 401 toast.
      await this.bootstrapSession();
      if (this.showLogin) {
        // Stay on the login overlay; everything else is gated.
        return;
      }
      await this.bootstrapAuthenticatedApp();
    },

    handleRoute() {
      const hash = location.hash || '#/';
      const m = hash.match(/^#\/projects\/(.+)$/);
      if (m) {
        const id = m[1];
        if (this.selectedProjectId !== id || this.view !== 'graph') {
          this.openProject(id);
        }
      } else {
        if (this.view !== 'list' && this.view !== 'settings') this.backToList(true);
      }
    },

    async authFetch(path, opts = {}) {
      const request = {
        ...opts,
        headers: { ...(opts.headers || {}) },
      };
      const token = localStorage.getItem('cairn.token');
      if (token) request.headers['Authorization'] = `Bearer ${token}`;
      let r = await fetch(path, request);
      // One transparent refresh on 401. If the user has no token or
      // the refresh itself fails, fall through to the error path so
      // the login overlay can be shown.
      if (r.status === 401 && token) {
        const refreshed = await this.refreshSession();
        if (refreshed) {
          const newToken = localStorage.getItem('cairn.token');
          request.headers['Authorization'] = `Bearer ${newToken}`;
          r = await fetch(path, request);
        }
      }
      return r;
    },

    async api(method, path, body) {
      const opts = { method, headers: { 'Content-Type': 'application/json' } };
      if (body) opts.body = JSON.stringify(body);
      const r = await this.authFetch(path, opts);
      if (r.status === 204) return null;
      const data = await r.json().catch(() => null);
      if (!r.ok) {
        if (r.status === 401) this.showLogin = true;
        let msg = `HTTP ${r.status}`;
        if (data && typeof data.detail === 'string') msg = data.detail;
        else if (data && Array.isArray(data.detail)) msg = data.detail.map(e => e.msg).join('; ');
        throw new Error(msg);
      }
      return data;
    },

    async refreshSession() {
      const current = localStorage.getItem('cairn.token');
      if (!current) return false;
      try {
        const r = await fetch('/auth/refresh', {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${current}` },
        });
        if (!r.ok) return false;
        const data = await r.json();
        if (data && data.access_token) {
          localStorage.setItem('cairn.token', data.access_token);
          return true;
        }
        return false;
      } catch (e) {
        return false;
      }
    },

    async login(email, password) {
      const r = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!r.ok) {
        const data = await r.json().catch(() => null);
        const detail = data && data.detail;
        throw new Error(typeof detail === 'string' ? detail : `HTTP ${r.status}`);
      }
      const data = await r.json();
      localStorage.setItem('cairn.token', data.access_token);
      this.currentUser = data.user;
      this.showLogin = false;
      await this.bootstrapAuthenticatedApp();
      return data;
    },

    async logout() {
      localStorage.removeItem('cairn.token');
      this.currentUser = null;
      this.showLogin = true;
    },

    async bootstrapSession() {
      // Used on first paint: if a token is sitting in localStorage,
      // try /auth/me to confirm it is still valid. If yes, hide the
      // login overlay; if no, surface the overlay.
      const token = localStorage.getItem('cairn.token');
      if (!token) {
        this.showLogin = true;
        return;
      }
      try {
        const r = await fetch('/auth/me', {
          headers: { 'Authorization': `Bearer ${token}` },
        });
        if (r.ok) {
          this.currentUser = await r.json();
          this.showLogin = false;
        } else {
          localStorage.removeItem('cairn.token');
          this.showLogin = true;
        }
      } catch (e) {
        this.showLogin = true;
      }
    },

    async bootstrapAuthenticatedApp() {
      await this.loadTaskTypes();
      await this.loadProjects();
      await this.loadSettings();
      this.startPolling();
      this.startLlmPolling();
      if (!this._hashChangeHandler) {
        this._hashChangeHandler = () => this.handleRoute();
        window.addEventListener('hashchange', this._hashChangeHandler);
      }
      this.appBootstrapped = true;
      this.handleRoute();
    },

    async fetchText(path) {
      const r = await this.authFetch(path, { method: 'GET' });
      const text = await r.text();
      if (!r.ok) {
        let detail = text;
        try {
          const data = JSON.parse(text);
          detail = data.detail || text;
        } catch {}
        throw new Error(detail || `HTTP ${r.status}`);
      }
      return text;
    },

    cloneData(value) {
      try {
        return JSON.parse(JSON.stringify(value));
      } catch (error) {
        if (typeof structuredClone === 'function') return structuredClone(value);
        throw error;
      }
    },

    loadScriptOnce(src) {
      if (this._loadedScriptUrls.has(src)) return Promise.resolve();
      if (this._scriptLoadPromises[src]) return this._scriptLoadPromises[src];
      this._scriptLoadPromises[src] = new Promise((resolve, reject) => {
        const existing = document.querySelector(`script[src="${src}"]`);
        if (existing) {
          existing.addEventListener('load', () => {
            this._loadedScriptUrls.add(src);
            resolve();
          }, { once: true });
          existing.addEventListener('error', () => reject(new Error(`Failed to load ${src}`)), { once: true });
          return;
        }
        const script = document.createElement('script');
        script.src = src;
        script.async = false;
        script.onload = () => {
          this._loadedScriptUrls.add(src);
          resolve();
        };
        script.onerror = () => reject(new Error(`Failed to load ${src}`));
        document.head.appendChild(script);
      });
      return this._scriptLoadPromises[src];
    },

    actorName() {
      return this.localPrefs.actor_name.trim() || 'Human';
    },

    canActOnSelectedFacts() {
      return this.projectIsActive() && this.selectedFacts.length > 0 && !this.selectedFacts.includes('goal');
    },

    escapeHtml(text) {
      return String(text ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    },

    async copyText(text) {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
      }
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.top = '0';
      textarea.style.left = '-9999px';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      textarea.setSelectionRange(0, textarea.value.length);
      try {
        if (!document.execCommand('copy')) {
          throw new Error('copy command rejected');
        }
      } finally {
        document.body.removeChild(textarea);
      }
    },

    async loadProxies() {
      try {
        this.proxies = await this.api('GET', '/proxies') || [];
      } catch (e) {
        console.error(e);
        this.proxies = [];
      }
    },

    taskTypeLabel(taskType) {
      const labels = { bootstrap: 'Bootstrap', explore: 'Intent', reason: 'Reason' };
      if (labels[taskType]) return labels[taskType];
      return String(taskType || '').replace(/[_-]+/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase());
    },

    roleDefaultTopLevelSkillIds() {
      return ['cypher-ctf', 'cypher-pentest', 'cypher-vuln-research'];
    },

    _expandRequiresForTask(task, kind, id, checked) {
      // Sub-skill auto expansion: when a skill is selected, automatically
      // add the requires_ids chain to the same task. When the user
      // unchecks, only the explicit user picks stay; the auto-added
      // chain is removed unless another parent still requires it.
      if (kind !== 'skill') return;
      const target = this._activeCapabilitiesTarget();
      const perTask = this.ensureTaskCapabilitiesMap(target);
      const entry = perTask[task];
      const userSet = new Set(entry.user_skill_ids || []);
      const skillsById = {};
      for (const item of this.capabilities?.catalog || []) {
        if (item.kind === 'skill') skillsById[item.id] = item;
      }
      const collected = new Set();
      const queue = checked && userSet.has(id) ? [id] : [];
      while (queue.length > 0) {
        const sid = queue.shift();
        if (collected.has(sid)) continue;
        collected.add(sid);
        const item = skillsById[sid];
        if (!item) continue;
        for (const child of (item.requires_ids || [])) {
          if (!collected.has(child) && skillsById[child]?.task_types?.includes(task)) {
            queue.push(child);
          }
        }
      }
      const union = new Set(checked ? collected : []);
      if (!checked && userSet.has(id)) {
        // Parent still user-picked: keep its sub-chain.
        for (const parent of userSet) {
          const item = skillsById[parent];
          if (!item) continue;
          const sub = [];
          const subQueue = [parent];
          const visited = new Set();
          while (subQueue.length > 0) {
            const cur = subQueue.shift();
            if (visited.has(cur)) continue;
            visited.add(cur);
            const it = skillsById[cur];
            if (!it) continue;
            for (const child of (it.requires_ids || [])) {
              if (!visited.has(child) && skillsById[child]?.task_types?.includes(task)) {
                sub.push(child);
                subQueue.push(child);
              }
            }
          }
          for (const child of sub) union.add(child);
        }
      }
      const candidates = new Set(union);
      const finalSet = new Set();
      for (const candidate of candidates) {
        const item = skillsById[candidate];
        if (!item) continue;
        if (!Array.isArray(item.task_types) || !item.task_types.includes(task)) continue;
        finalSet.add(candidate);
      }
      entry.skill_ids = Array.from(finalSet);
    },

    _refreshEffectiveTask(task) {
      const target = this._activeCapabilitiesTarget();
      const perTask = this.ensureTaskCapabilitiesMap(target);
      const entry = perTask[task];
      const userMcp = new Set(entry.user_mcp_server_ids || []);
      const userSkill = new Set(entry.user_skill_ids || []);
      const skillsById = {};
      for (const item of this.capabilities?.catalog || []) {
        if (item.kind === 'skill') skillsById[item.id] = item;
      }
      const expanded = new Set(userSkill);
      const queue = Array.from(userSkill);
      while (queue.length > 0) {
        const sid = queue.shift();
        const item = skillsById[sid];
        if (!item) continue;
        for (const child of (item.requires_ids || [])) {
          if (!expanded.has(child) && skillsById[child]?.task_types?.includes(task)) {
            expanded.add(child);
            queue.push(child);
          }
        }
      }
      entry.skill_ids = Array.from(expanded);
      entry.mcp_server_ids = Array.from(userMcp);
    },

    startPolling() {
      if (this.pollTimer) return;
      this.pollTimer = setInterval(async () => {
        if (!this.polling) return;
        if (this.projectPollInFlight) return;
        this.projectPollInFlight = true;
        try {
          if (this.selectedProjectId && this.view === 'graph' && this.project?.project) {
            const loaded = await this.loadProject(this.selectedProjectId);
            if (loaded) {
              if (this.sideTab === 'files') await this.loadProjectFiles(true);
              this.updateGraph();
            }
          } else {
            await this.loadProjects();
          }
        } finally {
          this.projectPollInFlight = false;
        }
      }, 5000);
    },

    parseBracketMeta(metaText) {
      const tokens = [];
      const text = (metaText || '').trim();
      let current = '';
      let quote = null;
      for (const ch of text) {
        if (quote) {
          current += ch;
          if (ch === quote) quote = null;
          continue;
        }
        if (ch === '"' || ch === '\'') {
          current += ch;
          quote = ch;
          continue;
        }
        if (/\s/.test(ch)) {
          if (current) {
            tokens.push(current);
            current = '';
          }
          continue;
        }
        current += ch;
      }
      if (current) tokens.push(current);

      const result = {};
      for (const token of tokens) {
        const idx = token.indexOf('=');
        if (idx <= 0) continue;
        const key = token.slice(0, idx);
        let value = token.slice(idx + 1).trim();
        if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith('\'') && value.endsWith('\''))) {
          value = value.slice(1, -1);
        }
        result[key] = value;
      }
      return result;
    },

    parseCypherSummary(text, expectedPrefix, mode) {
      const trimmed = (text || '').trim();
      if (!trimmed.startsWith(expectedPrefix)) return null;
      const closing = trimmed.indexOf(']');
      if (closing < 0) return null;
      const header = trimmed.slice(expectedPrefix.length, closing).trim();
      const rest = trimmed.slice(closing + 1).trim();
      return {
        mode,
        headline: rest.split(/\n+/)[0]?.trim() || '',
        body: rest,
        meta: this.parseBracketMeta(header),
        raw: trimmed,
      };
    },

    summaryView(text, kind = 'plain') {
      const trimmed = (text || '').trim();
      if (!trimmed) return { mode: 'plain', headline: '', body: '', meta: {}, raw: '' };
      if (kind === 'fact') {
        const finding = this.parseCypherSummary(trimmed, '[cypher:finding', 'cypher_finding');
        if (finding) return finding;
      }
      if (kind === 'intent' || kind === 'reason') {
        const intent = this.parseCypherSummary(trimmed, '[cypher:intent', 'cypher_intent');
        if (intent) return intent;
      }
      const replay = this.parseReplaySummary(trimmed);
      if (replay) return replay;
      return {
        mode: 'plain',
        headline: trimmed.split(/\n+/)[0]?.trim() || '',
        body: trimmed,
        meta: {},
        raw: trimmed,
      };
    },

    summaryHeadline(view) {
      return view?.headline || '';
    },

    summaryBody(view) {
      if (!view) return '';
      if (view.mode === 'plain') return view.body || '';
      const headline = view.headline || '';
      const body = view.body || '';
      if (!body) return '';
      return body === headline ? '' : body;
    },

    summaryMetaItems(view) {
      if (!view?.meta) return [];
      const entries = Object.entries(view.meta).filter(([, value]) => value !== null && value !== undefined && String(value).trim() !== '');
      const preferredOrder = ['type', 'confidence', 'severity', 'lane', 'priority', 'expected', 'cost', 'destructiveness', 'triggers', 'tags', 'artifacts', 'cleanup', 'expected_source_fact'];
      entries.sort((a, b) => {
        const aIdx = preferredOrder.indexOf(a[0]);
        const bIdx = preferredOrder.indexOf(b[0]);
        if (aIdx === -1 && bIdx === -1) return a[0].localeCompare(b[0]);
        if (aIdx === -1) return 1;
        if (bIdx === -1) return -1;
        return aIdx - bIdx;
      });
      return entries.map(([key, value]) => ({ key: key.replaceAll('_', ' '), value: String(value) }));
    },

    summaryHasMeta(view) {
      return this.summaryMetaItems(view).length > 0;
    },

    summaryCardViewModel(text, kind = 'plain') {
      const raw = String(text || '');
      const cacheKey = `${kind}:${raw}`;
      const cached = this._summaryCardCache.get(cacheKey);
      if (cached) return cached;
      const view = this.summaryView(raw, kind);
      const metaItems = this.summaryMetaItems(view);
      const model = {
        view,
        headline: this.summaryHeadline(view),
        body: this.summaryBody(view),
        metaItems,
        hasMeta: metaItems.length > 0,
      };
      this._summaryCardCache.set(cacheKey, model);
      this._summaryCardCacheOrder.push(cacheKey);
      while (this._summaryCardCacheOrder.length > 300) {
        const staleKey = this._summaryCardCacheOrder.shift();
        this._summaryCardCache.delete(staleKey);
      }
      return model;
    },

    formatTime(ts) { if (!ts) return ''; return new Date(ts).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'}); },
    formatDate(ts) { if (!ts) return ''; const d = new Date(ts); return d.toLocaleDateString([],{year:'numeric',month:'short',day:'numeric'}) + ' ' + d.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}); },
    formatDurationMs(ms) {
      const totalSeconds = Math.max(0, Math.round(ms / 1000));
      const hours = Math.floor(totalSeconds / 3600);
      const minutes = Math.floor((totalSeconds % 3600) / 60);
      const seconds = totalSeconds % 60;
      if (hours > 0) return `${hours}h ${minutes}m`;
      if (minutes > 0) return `${minutes}m ${seconds}s`;
      return `${seconds}s`;
    },

    formatBytes(bytes) {
      const value = Number(bytes || 0);
      if (value < 1024) return `${value} B`;
      const units = ['KB', 'MB', 'GB'];
      let size = value / 1024;
      let idx = 0;
      while (size >= 1024 && idx < units.length - 1) {
        size /= 1024;
        idx += 1;
      }
      return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[idx]}`;
    },

    async saveLocalSettings() {
      try {
        this.localPrefs.actor_name = this.actorName();
        this.localPrefs.layout_mode = this.isValidLayoutMode(this.localPrefs.layout_mode) ? this.localPrefs.layout_mode : 'dagre_tb';
        this.layoutMode = this.localPrefs.layout_mode;
        this.saveLocalPrefs();
        if (this.cy) {
          this.layoutLoading = true;
          await this.ensureLayoutEngineLoaded();
          this.cy.layout(this.layoutOpts()).run();
        }
        this.showLocalPrefs = false;
        this.showToast('Local preferences saved');
      } catch(e) { this.showToast(e.message, 'error'); }
      finally { this.layoutLoading = false; }
    },

  };
};
