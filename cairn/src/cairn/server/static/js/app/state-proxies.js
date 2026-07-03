export function createProxiesState() {
  const emptyServerForm = () => ({
    id: '', name: '', enabled: true, host: '', port: 22, username: '',
    password: '', private_key: '', cert_path: '', certificateFile: null, description: '',
  });
  const emptyProjectProxyForm = () => ({
    id: '', name: '', protocol: 'socks5h', host: '', port: 1080,
    auth_type: 'none', username: '', password: '', source: 'operator',
    lifecycle: 'persistent', description: '', scope: '',
    prerequisite_proxy_id: '', reachable_from: 'worker', usage_mode: 'tool_native_proxy',
  });
  return {
    resourceServers: [],
    serverForm: emptyServerForm(),
    serverFormOpen: false,
    serverFormEditId: '',
    proxyProjects: [],
    proxySelectedProjectId: '',
    proxySelectedProject: null,
    proxyProjectSearch: '',
    projectProxyEndpoints: [],
    projectProxyForm: emptyProjectProxyForm(),
    projectProxyFormOpen: false,

    async loadServers() {
      try {
        this.resourceServers = await this.api('GET', '/servers') || [];
      } catch (e) {
        console.error(e);
        this.resourceServers = [];
      }
    },

    async loadServersSettings() {
      await this.loadServers();
    },

    async loadProxySettings() {
      this.proxySelectedProjectId = '';
      this.proxySelectedProject = null;
      this.projectProxyEndpoints = [];
      this.cancelProjectProxyEdit();
      await this.loadProxyProjects();
    },

    async loadProxyProjects() {
      try {
        this.proxyProjects = await this.api('GET', '/projects') || [];
      } catch (e) {
        console.error(e);
        this.proxyProjects = [];
      }
    },

    filteredProxyProjects() {
      const query = (this.proxyProjectSearch || '').trim().toLowerCase();
      if (!query) return this.proxyProjects;
      return this.proxyProjects.filter(project => {
        const haystack = [
          project.id,
          project.title,
          project.status,
        ].filter(Boolean).join(' ').toLowerCase();
        return haystack.includes(query);
      });
    },

    async selectProxyProject(project) {
      this.proxySelectedProjectId = project.id;
      this.proxySelectedProject = project;
      this.cancelProjectProxyEdit();
      await this.loadProjectProxyEndpoints(project.id);
    },

    backToProxyProjects() {
      this.proxySelectedProjectId = '';
      this.proxySelectedProject = null;
      this.projectProxyEndpoints = [];
      this.cancelProjectProxyEdit();
    },

    async loadProjectProxyEndpoints(projectId = this.proxySelectedProjectId) {
      if (!projectId) {
        this.projectProxyEndpoints = [];
        return;
      }
      try {
        this.projectProxyEndpoints = await this.api('GET', `/projects/${encodeURIComponent(projectId)}/proxy-endpoints`) || [];
      } catch (e) {
        console.error(e);
        this.projectProxyEndpoints = [];
      }
    },

    openCreateServer() {
      this.serverForm = emptyServerForm();
      this.serverFormOpen = true;
      this.serverFormEditId = '';
    },

    openEditServer(server) {
      this.serverForm = {
        ...emptyServerForm(),
        ...server,
        password: '',
        private_key: '',
        certificateFile: null,
      };
      this.serverFormOpen = true;
      this.serverFormEditId = server.id;
    },

    cancelServerEdit() {
      this.serverForm = emptyServerForm();
      this.serverFormOpen = false;
      this.serverFormEditId = '';
    },

    async saveServerResource() {
      const existingAuth = this.serverFormEditId
        ? (this.resourceServers.find(server => server.id === this.serverFormEditId) || {})
        : {};
      const hasPassword = !!this.serverForm.password?.trim() || !!existingAuth.has_password;
      const hasPrivateKey = !!this.serverForm.private_key?.trim() || !!existingAuth.has_private_key;
      const hasCertificate = !!this.serverForm.certificateFile || !!existingAuth.cert_path;
      const auth_order = [];
      if (hasPrivateKey) auth_order.push('private_key');
      if (hasCertificate) auth_order.push('certificate');
      if (hasPassword) auth_order.push('password');
      const body = {
        id: this.serverForm.id.trim(),
        name: this.serverForm.name.trim(),
        enabled: !!this.serverForm.enabled,
        host: this.serverForm.host.trim(),
        port: Number(this.serverForm.port),
        username: this.serverForm.username.trim(),
        auth_order,
        description: this.serverForm.description?.trim() || '',
      };
      for (const key of ['password', 'private_key']) {
        const value = this.serverForm[key]?.trim();
        if (value) body[key] = value;
      }
      const formData = new FormData();
      formData.append('payload', JSON.stringify(body));
      if (this.serverForm.certificateFile) formData.append('certificate', this.serverForm.certificateFile);
      try {
        let response;
        if (this.serverFormEditId) {
          delete body.id;
          formData.set('payload', JSON.stringify(body));
          response = await this.authFetch(`/servers/${encodeURIComponent(this.serverFormEditId)}`, {
            method: 'PUT',
            body: formData,
          });
          if (!response.ok) throw await this.errorFromResponse(response);
          this.showToast('Server saved');
        } else {
          response = await this.authFetch('/servers/add', {
            method: 'POST',
            body: formData,
          });
          if (!response.ok) throw await this.errorFromResponse(response);
          this.showToast('Server created');
        }
        this.cancelServerEdit();
        await this.loadServers();
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async errorFromResponse(response) {
      const data = await response.json().catch(() => null);
      let message = `HTTP ${response.status}`;
      if (data && typeof data.detail === 'string') message = data.detail;
      else if (data && Array.isArray(data.detail)) message = data.detail.map(error => error.msg).join('; ');
      const error = new Error(message);
      error.status = response.status;
      return error;
    },

    async testServerResource(serverId) {
      try {
        const result = await this.api('POST', `/servers/${encodeURIComponent(serverId)}/test`, { command: 'true', timeout_seconds: 12 });
        await this.loadServers();
        this.showToast(result.ok ? 'Server test ok' : result.message || 'Server test failed', result.ok ? 'success' : 'error');
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async deleteServerResource(serverId, name) {
      if (!window.confirm(`Delete server "${name}"?`)) return;
      try {
        await this.api('DELETE', `/servers/${encodeURIComponent(serverId)}`);
        await this.loadServers();
        this.showToast('Server deleted');
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    openCreateProjectProxy() {
      if (!this.proxySelectedProjectId) return;
      this.projectProxyForm = emptyProjectProxyForm();
      this.projectProxyFormOpen = true;
    },

    openEditProjectProxy(endpoint) {
      this.projectProxyForm = { ...emptyProjectProxyForm(), ...endpoint, password: '' };
      this.projectProxyForm.prerequisite_proxy_id = endpoint.prerequisite_proxy_id || '';
      this.projectProxyFormOpen = true;
    },

    cancelProjectProxyEdit() {
      this.projectProxyForm = emptyProjectProxyForm();
      this.projectProxyFormOpen = false;
    },

    async saveProjectProxy() {
      if (!this.proxySelectedProjectId) return;
      const body = {
        name: this.projectProxyForm.name.trim(),
        protocol: this.projectProxyForm.protocol,
        host: this.projectProxyForm.host.trim(),
        port: Number(this.projectProxyForm.port),
        auth_type: this.projectProxyForm.auth_type,
        username: this.projectProxyForm.username || null,
        password: this.projectProxyForm.password || null,
        source: this.projectProxyForm.source || 'operator',
        lifecycle: this.projectProxyForm.lifecycle,
        description: this.projectProxyForm.description || '',
        scope: this.projectProxyForm.scope || '',
        prerequisite_proxy_id: this.projectProxyForm.prerequisite_proxy_id || null,
        reachable_from: this.projectProxyForm.reachable_from || 'worker',
        usage_mode: this.projectProxyForm.usage_mode || 'tool_native_proxy',
      };
      const base = `/projects/${encodeURIComponent(this.proxySelectedProjectId)}/proxy-endpoints`;
      try {
        if (this.projectProxyForm.id) {
          await this.api('PUT', `${base}/${encodeURIComponent(this.projectProxyForm.id)}`, body);
          this.showToast('Project proxy saved');
        } else {
          await this.api('POST', base, body);
          this.showToast('Project proxy registered');
        }
        this.cancelProjectProxyEdit();
        await this.loadProjectProxyEndpoints(this.proxySelectedProjectId);
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async deleteProjectProxy(endpointId, name) {
      if (!this.proxySelectedProjectId || !window.confirm(`Delete project proxy "${name}"?`)) return;
      try {
        await this.api('DELETE', `/projects/${encodeURIComponent(this.proxySelectedProjectId)}/proxy-endpoints/${encodeURIComponent(endpointId)}`);
        await this.loadProjectProxyEndpoints(this.proxySelectedProjectId);
        this.showToast('Project proxy deleted');
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async resolveProjectProxyChain(endpointId) {
      try {
        const result = await this.api('GET', `/projects/${encodeURIComponent(this.proxySelectedProjectId)}/proxy-endpoints/${encodeURIComponent(endpointId)}/resolve-chain`);
        const names = (result.chain || []).map(item => item.name || item.id).join(' -> ');
        this.showToast(result.ok ? `Chain: ${names || endpointId}` : result.reason, result.ok ? 'success' : 'error');
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },
  };
}
