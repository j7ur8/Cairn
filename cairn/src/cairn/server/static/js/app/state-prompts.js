export function createPromptsState() {
  return {
    promptTemplateNames: [],
    promptTemplateSelected: 'bootstrap.md',
    promptTemplateDetail: null,
    rolePromptDetail: null,
    promptCapabilityCatalog: [],
    promptRoleRequiredSkillIds: [],
    promptEditorContent: '',
    promptEditorSaving: false,
    promptEditorLoading: false,

    async loadPrompts() {
      this.promptEditorLoading = true;
      try {
        await this.loadPromptGroup();
      } catch(e) {
        this.showToast(e.message, 'error');
      } finally {
        this.promptEditorLoading = false;
      }
    },

    async loadPromptGroup() {
      this.promptEditorLoading = true;
      try {
        const [detail, roles, catalog] = await Promise.all([
          this.api('GET', '/prompt-templates'),
          this.api('GET', '/role-prompts'),
          this.api('GET', '/capabilities/catalog'),
        ]);
        this.promptTemplateDetail = detail;
        this.rolePromptDetail = roles || { role_names: [], roles: {}, role_sha256: {}, role_metadata: {} };
        this.promptCapabilityCatalog = Array.isArray(catalog) ? catalog : [];
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
        this.syncPromptRoleRequiredSkills();
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
      return `prompts/${path}`;
    },

    promptEditorResources() {
      const detail = this.promptTemplateDetail || {};
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
          metadata: roles.role_metadata?.[name] || null,
        })),
      ];
    },

    promptResourceDisplayName(resource) {
      if (!resource) return '';
      const pathSegments = String(resource.path || '').split('/').filter(Boolean);
      const keySegments = String(resource.key || '').split('/').filter(Boolean);
      const segments = pathSegments.length > 0 ? pathSegments : keySegments;
      const basename = segments[segments.length - 1] || '';
      if (resource.type === 'prompt') return basename;
      if (resource.type === 'role') {
        const parent = segments[segments.length - 2] || '';
        if (basename === 'ROLE.md' && parent) return parent;
        return parent || basename;
      }
      return basename;
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
      return this.promptTemplateDetail?.prompts?.[resource.path] || '';
    },

    promptSelectedWritable() {
      const resource = this.promptSelectedResource();
      return !!resource && resource.writable !== false;
    },

    promptSelectedIsRole() {
      return this.promptSelectedResource()?.type === 'role';
    },

    promptSelectedRoleMetadata() {
      const resource = this.promptSelectedResource();
      if (!resource || resource.type !== 'role') return null;
      return this.rolePromptDetail?.role_metadata?.[resource.path] || resource.metadata || null;
    },

    promptSelectedRoleName() {
      const meta = this.promptSelectedRoleMetadata();
      if (meta?.name) return meta.name;
      return this.promptResourceDisplayName(this.promptSelectedResource());
    },

    promptAvailableSkillOptions() {
      return (this.promptCapabilityCatalog || [])
        .filter(item => item && item.kind === 'skill')
        .sort((a, b) => String(a.name || a.id || '').localeCompare(String(b.name || b.id || '')));
    },

    promptRoleCanEditRequiredSkills() {
      return !!this.promptSelectedRoleMetadata()?.role_id;
    },

    syncPromptRoleRequiredSkills() {
      const meta = this.promptSelectedRoleMetadata();
      this.promptRoleRequiredSkillIds = Array.isArray(meta?.default_skill_ids)
        ? [...meta.default_skill_ids]
        : [];
    },

    selectPromptTemplate(name) {
      const key = typeof name === 'string' ? name : name?.key;
      if (!this.promptTemplateNames.includes(key)) return;
      this.promptTemplateSelected = key;
      this.promptEditorContent = this.promptSelectedResourceContent();
      this.syncPromptRoleRequiredSkills();
    },

    promptTemplateSha(name = this.promptTemplateSelected) {
      const key = typeof name === 'string' ? name : name?.key;
      const resource = this.promptEditorResources().find(item => item.key === key);
      return resource?.sha || '';
    },

    promptTemplateSetSha() {
      return this.promptTemplateDetail?.prompts_sha256 || '';
    },

    promptTemplateRoutePath(name) {
      return String(name || '').split('/').map(segment => encodeURIComponent(segment)).join('/');
    },

    async savePromptTemplate() {
      const resource = this.promptSelectedResource();
      if (!resource || resource.writable === false) return;
      this.promptEditorSaving = true;
      const submittedContent = this.promptEditorContent || '';
      const submittedSkillIds = [...(this.promptRoleRequiredSkillIds || [])];
      try {
        if (resource.type === 'role') {
          const meta = this.promptSelectedRoleMetadata();
          const promptDetail = await this.api(
            'PUT',
            `/role-prompts/${this.promptTemplateRoutePath(resource.path)}`,
            { content: submittedContent },
          );
          let updatedRole = null;
          if (meta?.role_id) {
            updatedRole = await this.api(
              'PUT',
              `/roles/admin/${encodeURIComponent(meta.role_id)}/default-skills`,
              { default_skill_ids: submittedSkillIds },
            );
          }
          const detail = promptDetail;
          if (updatedRole) {
            detail.role_metadata = detail.role_metadata || {};
            detail.role_metadata[resource.path] = {
              ...(detail.role_metadata[resource.path] || {}),
              role_id: updatedRole.id,
              name: updatedRole.name,
              default_skill_ids: updatedRole.default_skill_ids || [],
              available: updatedRole.available,
            };
          }
          this.rolePromptDetail = detail;
          this.promptTemplateNames = this.promptEditorResources().map(item => item.key);
          this.promptEditorContent = submittedContent;
          this.promptRoleRequiredSkillIds = submittedSkillIds;
          this.showToast('Role prompt saved');
        } else {
          const detail = await this.api(
            'PUT',
            `/prompt-templates/templates/${this.promptTemplateRoutePath(resource.path)}`,
            { content: this.promptEditorContent || '' },
          );
          this.promptTemplateDetail = detail;
          this.promptTemplateNames = this.promptEditorResources().map(item => item.key);
          this.promptEditorContent = this.promptTemplateDetail?.prompts?.[resource.path] || '';
          this.showToast('Prompt template saved');
        }
      } catch(e) {
        this.showToast(e.message, 'error');
      } finally {
        this.promptEditorSaving = false;
      }
    },
  };
}
