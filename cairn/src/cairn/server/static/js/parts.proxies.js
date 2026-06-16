window.CairnParts = window.CairnParts || {};
CairnParts.proxies = function () {
  return {
    proxyForm: { id: '', name: '', type: 'socks5', host: '', port: 1080, username: '', password: '' },
    proxyFormOpen: false,

    resetProxyForm() {
      this.proxyForm = { id: '', name: '', type: 'socks5', host: '', port: 1080, username: '', password: '' };
      this.proxyFormOpen = false;
    },

    openCreateProxy() {
      this.resetProxyForm();
      this.proxyFormOpen = true;
    },

    async openEditProxy(proxyId) {
      try {
        const p = await this.api('GET', `/proxies/${encodeURIComponent(proxyId)}`);
        this.proxyForm = {
          id: p.id,
          name: p.name || '',
          type: p.type || 'socks5',
          host: p.host || '',
          port: p.port || 1080,
          username: p.username || '',
          password: p.password || '',
        };
        this.proxyFormOpen = true;
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    cancelProxyEdit() {
      this.resetProxyForm();
    },

    async saveProxy() {
      const body = {
        name: this.proxyForm.name.trim(),
        type: this.proxyForm.type,
        host: this.proxyForm.host.trim(),
        port: Number(this.proxyForm.port),
        username: this.proxyForm.username || null,
        password: this.proxyForm.password || null,
      };
      try {
        if (this.proxyForm.id) {
          await this.api('PUT', `/proxies/${encodeURIComponent(this.proxyForm.id)}`, body);
          this.showToast('Proxy saved');
        } else {
          await this.api('POST', '/proxies', body);
          this.showToast('Proxy created');
        }
        this.resetProxyForm();
        await this.loadProxies();
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },

    async deleteProxy(proxyId, proxyName) {
      const ok = window.confirm(`Delete proxy "${proxyName}"? Projects that reference it will fall back to direct connection.`);
      if (!ok) return;
      try {
        await this.api('DELETE', `/proxies/${encodeURIComponent(proxyId)}`);
        this.showToast('Proxy deleted');
        if (this.proxyForm.id === proxyId) this.resetProxyForm();
        await this.loadProxies();
        if (this.newProject && this.newProject.proxy_id === proxyId) this.newProject.proxy_id = '';
      } catch (e) {
        this.showToast(e.message, 'error');
      }
    },
  };
};
