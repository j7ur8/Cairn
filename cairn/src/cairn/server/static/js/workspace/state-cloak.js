export function createWorkspaceCloakState() {
  return {
    cloakSidecar: null,
    cloakSidecarLoading: false,

    async loadCloakSidecar(projectId = this.selectedProjectId) {
      if (!projectId) {
        this.cloakSidecar = null;
        return null;
      }
      try {
        this.cloakSidecarLoading = true;
        const status = await this.api('GET', `/projects/${projectId}/cloak-sidecar`);
        if (projectId === this.selectedProjectId) this.cloakSidecar = status;
        return status;
      } catch (error) {
        if (projectId === this.selectedProjectId) {
          this.cloakSidecar = {
            running: false,
            enabled: false,
            novnc_url: null,
            slots: 0,
            busy_slots: 0,
            error: error.message || String(error),
          };
        }
        return null;
      } finally {
        this.cloakSidecarLoading = false;
      }
    },

    cloakButtonVisible() {
      return Boolean(this.cloakSidecar?.enabled);
    },

    cloakButtonDisabled() {
      return !this.cloakSidecar?.running || !this.cloakSidecar?.novnc_url;
    },

    cloakButtonTitle() {
      if (this.cloakSidecarLoading) return 'Loading Cloak UI status';
      if (!this.cloakSidecar?.enabled) return 'Cloak sidecar is not configured';
      if (!this.cloakSidecar?.running) return this.cloakSidecar?.error || 'Cloak sidecar is not running';
      if (!this.cloakSidecar?.novnc_url) return 'Cloak noVNC URL is unavailable';
      return `${this.cloakSidecar.busy_slots || 0}/${this.cloakSidecar.slots || 0} slots busy`;
    },

    openCloakUi() {
      if (this.cloakButtonDisabled()) return;
      window.open(this.cloakSidecar.novnc_url, '_blank', 'noopener,noreferrer');
    },
  };
}
