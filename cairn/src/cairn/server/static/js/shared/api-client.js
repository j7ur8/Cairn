function authHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function createApiClient({
  fetchImpl = globalThis.fetch,
  getToken = () => localStorage.getItem('cairn.token'),
  setToken = token => localStorage.setItem('cairn.token', token),
  clearToken = () => localStorage.removeItem('cairn.token'),
} = {}) {
  return {
    async authFetch(path, opts = {}) {
      const request = {
        ...opts,
        headers: { ...(opts.headers || {}) },
      };
      const token = getToken();
      Object.assign(request.headers, authHeaders(token));
      let response = await fetchImpl(path, request);
      if (response.status === 401 && token) {
        const refreshed = await this.refreshSession();
        if (refreshed) {
          Object.assign(request.headers, authHeaders(getToken()));
          response = await fetchImpl(path, request);
        }
      }
      return response;
    },

    async api(method, path, body) {
      const opts = { method, headers: { 'Content-Type': 'application/json' } };
      if (body) opts.body = JSON.stringify(body);
      const response = await this.authFetch(path, opts);
      if (response.status === 204) return null;
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        let message = `HTTP ${response.status}`;
        if (data && typeof data.detail === 'string') message = data.detail;
        else if (data && Array.isArray(data.detail)) message = data.detail.map(error => error.msg).join('; ');
        const error = new Error(message);
        error.status = response.status;
        throw error;
      }
      return data;
    },

    async refreshSession() {
      const current = getToken();
      if (!current) return false;
      try {
        const response = await fetchImpl('/auth/refresh', {
          method: 'POST',
          headers: authHeaders(current),
        });
        if (!response.ok) return false;
        const data = await response.json();
        if (data && data.access_token) {
          setToken(data.access_token);
          return true;
        }
        return false;
      } catch (error) {
        return false;
      }
    },

    async login(email, password) {
      const response = await fetchImpl('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        const detail = data && data.detail;
        throw new Error(typeof detail === 'string' ? detail : `HTTP ${response.status}`);
      }
      const data = await response.json();
      setToken(data.access_token);
      return data;
    },

    async me() {
      const token = getToken();
      if (!token) return null;
      try {
        const response = await fetchImpl('/auth/me', {
          headers: authHeaders(token),
        });
        if (!response.ok) {
          clearToken();
          return null;
        }
        return await response.json();
      } catch (error) {
        return null;
      }
    },

    logout() {
      clearToken();
    },
  };
}
