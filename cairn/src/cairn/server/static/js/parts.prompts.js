window.CairnParts = window.CairnParts || {};
CairnParts.prompts = function () {
  return {
    promptTemplateNames: [],
    promptGroups: [],
    promptGroupSelected: '',
    promptTemplateSelected: 'bootstrap.md',
    promptGroupDetail: null,
    rolePromptDetail: null,
    promptEditorContent: '',
    promptEditorSaving: false,
    promptEditorLoading: false,

    async loadPromptGroups() {
      this.promptEditorLoading = true;
      try {
        if (!this.runtimeLimitsForm.prompt_group) await this.loadRuntimeLimits();
        const data = await this.api('GET', '/prompt-groups');
        this.promptGroups = Array.isArray(data.groups) ? data.groups : [];
        if (!this.promptGroupSelected) {
          this.promptGroupSelected = this.runtimeLimitsForm.prompt_group || this.promptGroups[0] || '';
        }
        if (this.promptGroupSelected) await this.loadPromptGroup(this.promptGroupSelected);
      } catch(e) {
        this.showToast(e.message, 'error');
      } finally {
        this.promptEditorLoading = false;
      }
    },

    async loadPromptGroup(group = this.promptGroupSelected) {
      if (!group) return;
      this.promptGroupSelected = group;
      this.promptEditorLoading = true;
      try {
        const [detail, roles] = await Promise.all([
          this.api('GET', `/prompt-groups/${encodeURIComponent(group)}`),
          this.api('GET', '/role-prompts'),
        ]);
        this.promptGroupDetail = detail;
        this.rolePromptDetail = roles || { role_names: [], roles: {}, role_sha256: {} };
        const promptNames = this.sortedPromptTemplateNames(
          Array.isArray(detail.prompt_names) ? detail.prompt_names : Object.keys(detail.prompts || {}),
        );
        this.promptTemplateNames = [
          ...promptNames.map(name => this.promptResourceKey('prompt', name)),
          ...this.sortedRolePromptNames(
            Array.isArray(this.rolePromptDetail.role_names)
              ? this.rolePromptDetail.role_names
              : Object.keys(this.rolePromptDetail.roles || {}),
          ).map(name => this.promptResourceKey('role', name)),
        ];
        if (!this.promptTemplateNames.includes(this.promptTemplateSelected)) {
          const legacySelected = this.promptTemplateNames.includes(this.promptResourceKey('prompt', this.promptTemplateSelected))
            ? this.promptResourceKey('prompt', this.promptTemplateSelected)
            : '';
          this.promptTemplateSelected = legacySelected || this.promptTemplateNames[0] || '';
        }
        this.promptEditorContent = this.promptSelectedResourceContent();
      } catch(e) {
        this.showToast(e.message, 'error');
      } finally {
        this.promptEditorLoading = false;
      }
    },

    sortedPromptTemplateNames(names) {
      const coreOrder = ['bootstrap.md', 'bootstrap_conclude.md', 'explore.md', 'explore_conclude.md', 'reason.md'];
      const coreIndex = name => coreOrder.indexOf(name);
      return [...new Set(names || [])].sort((a, b) => {
        const ai = coreIndex(a);
        const bi = coreIndex(b);
        if (ai >= 0 || bi >= 0) {
          if (ai >= 0 && bi >= 0) return ai - bi;
          return ai >= 0 ? -1 : 1;
        }
        return a.localeCompare(b);
      });
    },

    sortedRolePromptNames(names) {
      return [...new Set(names || [])].sort((a, b) => a.localeCompare(b));
    },

    promptResourceKey(type, path) {
      if (type === 'role') return `roles/${path}`;
      return `prompts/${this.promptGroupSelected}/${path}`;
    },

    promptEditorResources() {
      const detail = this.promptGroupDetail || {};
      const roles = this.rolePromptDetail || {};
      const promptNames = this.sortedPromptTemplateNames(
        Array.isArray(detail.prompt_names) ? detail.prompt_names : Object.keys(detail.prompts || {}),
      );
      const roleNames = this.sortedRolePromptNames(
        Array.isArray(roles.role_names) ? roles.role_names : Object.keys(roles.roles || {}),
      );
      return [
        ...promptNames.map(name => ({
          type: 'prompt',
          path: name,
          key: this.promptResourceKey('prompt', name),
          groupLabel: 'Prompt Templates',
          writable: true,
          sha: detail.prompt_sha256?.[name] || '',
        })),
        ...roleNames.map(name => ({
          type: 'role',
          path: name,
          key: this.promptResourceKey('role', name),
          groupLabel: 'Role Prompts',
          writable: true,
          sha: roles.role_sha256?.[name] || '',
        })),
      ];
    },

    promptResourceDisplayName(resource) {
      if (!resource) return '';
      if (resource.type === 'role') return `roles/${resource.path}`;
      return `prompts/${this.promptGroupSelected}/${resource.path}`;
    },

    promptShowResourceGroup(resource, index) {
      if (index === 0) return true;
      const previous = this.promptEditorResources()[index - 1];
      return !previous || previous.type !== resource.type;
    },

    promptSelectedResource() {
      return this.promptEditorResources().find(resource => resource.key === this.promptTemplateSelected) || null;
    },

    promptSelectedResourceContent() {
      const resource = this.promptSelectedResource();
      if (!resource) return '';
      if (resource.type === 'role') return this.rolePromptDetail?.roles?.[resource.path] || '';
      return this.promptGroupDetail?.prompts?.[resource.path] || '';
    },

    promptSelectedWritable() {
      const resource = this.promptSelectedResource();
      return !!resource && resource.writable !== false;
    },

    selectPromptTemplate(name) {
      const key = typeof name === 'string' ? name : name?.key;
      if (!this.promptTemplateNames.includes(key)) return;
      this.promptTemplateSelected = key;
      this.promptEditorContent = this.promptSelectedResourceContent();
    },

    promptTemplateSha(name = this.promptTemplateSelected) {
      const key = typeof name === 'string' ? name : name?.key;
      const resource = this.promptEditorResources().find(item => item.key === key);
      return resource?.sha || '';
    },

    promptGroupSha() {
      return this.promptGroupDetail?.prompts_sha256 || '';
    },

    promptTemplateRoutePath(name) {
      return String(name || '').split('/').map(segment => encodeURIComponent(segment)).join('/');
    },

    async savePromptTemplate() {
      const resource = this.promptSelectedResource();
      if (!this.promptGroupSelected || !resource || resource.writable === false) return;
      this.promptEditorSaving = true;
      try {
        if (resource.type === 'role') {
          const detail = await this.api(
            'PUT',
            `/role-prompts/${this.promptTemplateRoutePath(resource.path)}`,
            { content: this.promptEditorContent || '' },
          );
          this.rolePromptDetail = detail;
          this.promptTemplateNames = this.promptEditorResources().map(item => item.key);
          this.promptEditorContent = this.rolePromptDetail?.roles?.[resource.path] || '';
          this.showToast('Role prompt saved');
        } else {
          const detail = await this.api(
            'PUT',
            `/prompt-groups/${encodeURIComponent(this.promptGroupSelected)}/templates/${this.promptTemplateRoutePath(resource.path)}`,
            { content: this.promptEditorContent || '' },
          );
          this.promptGroupDetail = detail;
          this.promptTemplateNames = this.promptEditorResources().map(item => item.key);
          this.promptEditorContent = this.promptGroupDetail?.prompts?.[resource.path] || '';
          this.showToast('Prompt template saved');
        }
      } catch(e) {
        this.showToast(e.message, 'error');
      } finally {
        this.promptEditorSaving = false;
      }
    },
  };
};
