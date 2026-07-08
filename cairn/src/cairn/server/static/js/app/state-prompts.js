export function createPromptsState() {
  return {
    promptTemplateNames: [],
    promptTemplateSelected: '',
    promptActivePhase: 'bootstrap',
    promptTemplateDetail: null,
    rolePromptDetail: null,
    promptInstructionPreviewDetail: null,
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
        const [detail, roles, catalog, previews] = await Promise.all([
          this.api('GET', '/prompt-templates'),
          this.api('GET', '/role-prompts'),
          this.api('GET', '/capabilities/catalog'),
          this.api('GET', '/prompt-instruction-previews'),
        ]);
        this.promptTemplateDetail = detail;
        this.rolePromptDetail = roles || { role_names: [], roles: {}, role_sha256: {}, role_metadata: {} };
        this.promptInstructionPreviewDetail = previews || { phases: [] };
        this.promptCapabilityCatalog = Array.isArray(catalog) ? catalog : [];
        this.promptTemplateNames = this.promptEditorResources().map(item => item.key);
        if (!this.promptTemplateNames.includes(this.promptTemplateSelected)) {
          this.promptTemplateSelected = this.promptTemplateNames[0] || '';
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
      const phase = arguments.length > 2 ? arguments[2] : '';
      if (type === 'role') return this.normalizedRolePromptPath(path, phase);
      const category = type === 'prompt' ? 'common' : (type === 'runtime' ? 'instruction' : (type === 'role' ? 'roles' : type));
      return `${phase || 'bootstrap'}/${category}/${path}`;
    },

    normalizedRolePromptPath(path, phase = 'bootstrap') {
      const raw = String(path || '').trim();
      const parts = raw.split('/').filter(Boolean);
      const knownPhases = ['bootstrap', 'explore', 'reason'];
      const selectedPhase = knownPhases.includes(String(phase))
        ? String(phase)
        : (knownPhases.includes(parts[0]) ? parts[0] : 'bootstrap');
      let filename = parts[parts.length - 1] || '';
      if (!filename) return `${selectedPhase}/roles/`;
      if (!filename.endsWith('.md')) filename = `${filename}.md`;
      return `${selectedPhase}/roles/${filename}`;
    },

    refreshPromptSelectionAfterSave(resource, expectedContent) {
      this.promptTemplateNames = this.promptEditorResources().map(item => item.key);
      if (!this.promptTemplateNames.includes(resource.key)) {
        throw new Error('Saved prompt was not returned by server.');
      }
      this.promptTemplateSelected = resource.key;
      const content = this.promptSelectedResourceContent();
      if (typeof expectedContent === 'string' && content !== expectedContent) {
        throw new Error('Saved prompt response did not include the updated content.');
      }
      this.promptEditorContent = content;
      this.syncPromptRoleRequiredSkills();
    },

    promptEditorResources() {
      const detail = this.promptTemplateDetail || {};
      const roles = this.rolePromptDetail || {};
      const previews = this.promptInstructionPreviewDetail || {};
      const promptResources = Array.isArray(detail.resources) && detail.resources.length > 0
        ? detail.resources.map(resource => ({
          type: 'prompt',
          phase: resource.phase || 'bootstrap',
          category: 'common',
          path: resource.path || resource.logical_name || '',
          logicalName: resource.logical_name || resource.path || '',
          key: this.promptResourceKey('prompt', resource.path || resource.logical_name || '', resource.phase || 'bootstrap'),
          groupLabel: 'Common Prompt',
          writable: resource.writable !== false,
          sha: resource.sha256 || '',
          content: resource.content || '',
        }))
        : this.sortedPromptTemplateNames(Array.isArray(detail.prompt_names) ? detail.prompt_names : Object.keys(detail.prompts || {})).map(name => ({
          type: 'prompt',
          phase: name.startsWith('explore') ? 'explore' : (name.startsWith('reason') ? 'reason' : 'bootstrap'),
          category: 'common',
          path: name,
          logicalName: name,
          key: this.promptResourceKey('prompt', name, name.startsWith('explore') ? 'explore' : (name.startsWith('reason') ? 'reason' : 'bootstrap')),
          groupLabel: 'Common Prompt',
          writable: true,
          sha: detail.prompt_sha256?.[name] || '',
        }));
      const roleResources = Array.isArray(roles.resources) && roles.resources.length > 0
        ? roles.resources.map(resource => {
          const phase = resource.phase || String(resource.path || '').split('/')[0] || 'bootstrap';
          const path = this.normalizedRolePromptPath(resource.path || resource.logical_name || '', phase);
          return {
            type: 'role',
            phase,
            category: 'roles',
            path,
            logicalName: resource.logical_name || path,
            key: this.promptResourceKey('role', path, phase),
            groupLabel: 'Role Prompt',
            writable: resource.writable !== false,
            sha: resource.sha256 || roles.role_sha256?.[path] || '',
            content: resource.content || roles.roles?.[path] || '',
            metadata: resource.role_metadata || roles.role_metadata?.[path] || roles.role_metadata?.[resource.path] || null,
          };
        })
        : this.sortedRolePromptNames(Array.isArray(roles.role_names) ? roles.role_names : Object.keys(roles.roles || {})).map(name => {
          const phase = String(name).split('/')[0] || 'bootstrap';
          const path = this.normalizedRolePromptPath(name, phase);
          return {
            type: 'role',
            phase,
            category: 'roles',
            path,
            logicalName: path,
            key: this.promptResourceKey('role', path, phase),
            groupLabel: 'Role Prompt',
            writable: true,
            sha: roles.role_sha256?.[path] || roles.role_sha256?.[name] || '',
            content: roles.roles?.[path] || roles.roles?.[name] || '',
            metadata: roles.role_metadata?.[path] || roles.role_metadata?.[name] || null,
          };
        });
      const instructionResources = (Array.isArray(previews.resources) && previews.resources.length > 0
        ? previews.resources
        : (Array.isArray(previews.phases) ? previews.phases : []).flatMap(phase => {
            const phaseName = String(phase?.phase || '');
            return (Array.isArray(phase?.files) ? phase.files : []).map(file => ({
              phase: phaseName,
              category: 'instruction',
              path: String(file?.path || ''),
              logical_name: String(file?.path || ''),
              content: file?.content || '',
              sha256: file?.sha256 || '',
              writable: file?.writable !== false,
            }));
          })).map(resource => ({
            type: 'runtime',
            phase: resource.phase || 'bootstrap',
            category: 'instruction',
            path: resource.path || resource.logical_name || 'Instruction.md',
            logicalName: resource.logical_name || resource.path || 'Instruction.md',
            key: this.promptResourceKey('runtime', resource.path || resource.logical_name || 'Instruction.md', resource.phase || 'bootstrap'),
            groupLabel: 'Instruction Prompt',
            writable: resource.writable !== false,
            sha: resource.sha256 || '',
            content: resource.content || '',
          }));
      return [...promptResources, ...roleResources, ...instructionResources]
        .filter(resource => resource.phase === this.promptActivePhase);
    },

    promptResourceDisplayName(resource) {
      if (!resource) return '';
      const pathSegments = String(resource.path || '').split('/').filter(Boolean);
      const keySegments = String(resource.key || '').split('/').filter(Boolean);
      const segments = pathSegments.length > 0 ? pathSegments : keySegments;
      const basename = segments[segments.length - 1] || '';
      if (resource.type === 'prompt') return resource.logicalName || basename;
      if (resource.type === 'role') {
        return basename.replace(/\.md$/, '');
      }
      if (resource.type === 'runtime') return resource.path;
      return basename;
    },

    promptShowResourceGroup(resource, index) {
      if (index === 0) return true;
      const previous = this.promptEditorResources()[index - 1];
      return !previous || previous.groupLabel !== resource.groupLabel;
    },

    promptSelectedResource() {
      return this.promptEditorResources().find(resource => resource.key === this.promptTemplateSelected) || null;
    },

    promptSelectedResourceContent() {
      const resource = this.promptSelectedResource();
      if (!resource) return '';
      if (resource.type === 'role') return this.rolePromptDetail?.roles?.[resource.path] || resource.content || '';
      if (resource.type === 'runtime') return resource.content || '';
      return this.promptTemplateDetail?.prompts?.[resource.path] || resource.content || '';
    },

    promptSelectedWritable() {
      const resource = this.promptSelectedResource();
      return !!resource && resource.writable !== false;
    },

    promptSelectedIsRole() {
      const resource = this.promptSelectedResource();
      return resource?.type === 'role' && !!this.promptSelectedRoleMetadata();
    },

    promptSelectedRoleMetadata() {
      const resource = this.promptSelectedResource();
      if (!resource || resource.type !== 'role') return null;
      if (this.rolePromptDetail?.role_metadata_error) return null;
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
      return !this.promptRoleMetadataError() && !!this.promptSelectedRoleMetadata()?.role_id;
    },

    promptRoleMetadataError() {
      return this.rolePromptDetail?.role_metadata_error || '';
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

    selectPromptPhase(phase) {
      if (!['bootstrap', 'explore', 'reason'].includes(phase)) return;
      this.promptActivePhase = phase;
      this.promptTemplateNames = this.promptEditorResources().map(item => item.key);
      this.promptTemplateSelected = this.promptTemplateNames[0] || '';
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
          if (!meta?.role_id) {
            throw new Error(this.promptRoleMetadataError() || 'No role configuration is linked to this prompt.');
          }
          const detail = await this.api(
            'PUT',
            `/roles/admin/${encodeURIComponent(meta.role_id)}/prompt-settings`,
            { content: submittedContent, default_skill_ids: submittedSkillIds, phase: resource.phase },
          );
          this.rolePromptDetail = detail;
          this.refreshPromptSelectionAfterSave(resource, submittedContent);
          this.showToast('Role prompt saved');
        } else if (resource.type === 'runtime') {
          const detail = await this.api(
            'PUT',
            `/prompt-instruction-previews/${encodeURIComponent(resource.phase)}/${this.promptTemplateRoutePath(resource.path)}`,
            { content: this.promptEditorContent || '' },
          );
          this.promptInstructionPreviewDetail = detail;
          this.refreshPromptSelectionAfterSave(resource, submittedContent);
          this.showToast('Runtime instruction template saved');
        } else {
          const detail = await this.api(
            'PUT',
            `/prompt-templates/templates/${this.promptTemplateRoutePath(resource.path)}`,
            { content: this.promptEditorContent || '' },
          );
          this.promptTemplateDetail = detail;
          this.refreshPromptSelectionAfterSave(resource, submittedContent);
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
