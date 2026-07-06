import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const JS_ROOT = resolve(ROOT, 'src/cairn/server/static/js');
const STATE_FILE_MAX_LINES = 1200;

function walkJsFiles(dir) {
  const files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const fullPath = resolve(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walkJsFiles(fullPath));
    } else if (entry.isFile() && fullPath.endsWith('.js')) {
      files.push(fullPath);
    }
  }
  return files.sort();
}

function countLines(path) {
  const text = readFileSync(path, 'utf8');
  if (text.length === 0) return 0;
  return text.endsWith('\n') ? text.split('\n').length - 1 : text.split('\n').length;
}

function checkSyntax(files) {
  for (const file of files) {
    execFileSync(process.execPath, ['--check', file], { stdio: 'pipe' });
  }
}

function checkStateFileSizes(files) {
  const offenders = files
    .filter(file => /(?:^|[/\\])state-[^/\\]+\.js$/.test(file))
    .map(file => ({ file, lines: countLines(file) }))
    .filter(item => item.lines > STATE_FILE_MAX_LINES);
  assert.deepEqual(
    offenders,
    [],
    `state files must stay below ${STATE_FILE_MAX_LINES} lines: ${
      offenders.map(item => `${relative(ROOT, item.file)} (${item.lines})`).join(', ')
    }`,
  );
}

function checkLocalImportsResolve(files) {
  const importRe = /(?:import|export)\s+(?:[^'"]*\s+from\s+)?['"]([^'"]+)['"]/g;
  const offenders = [];
  for (const file of files) {
    const source = readFileSync(file, 'utf8');
    for (const match of source.matchAll(importRe)) {
      const specifier = match[1];
      if (!specifier.startsWith('.')) continue;
      const target = resolve(dirname(file), specifier);
      if (!existsSync(target)) {
        offenders.push(`${relative(ROOT, file)} -> ${specifier}`);
      }
    }
  }
  assert.deepEqual(offenders, [], `local JS imports must resolve: ${offenders.join(', ')}`);
}

function checkNoDuplicateKeys() {
  runModuleAssertion(`
    import assert from 'node:assert/strict';
    import { createAppState } from './src/cairn/server/static/js/app/create-app-state.js';

    globalThis.CAIRN_FRONTEND_ENV = 'development';
    assert.throws(
      () => createAppState({ one: 1 }, { two: 2, one: 3 }),
      /duplicate app state key overwritten: one/,
    );
    assert.doesNotThrow(() => createAppState({ one: 1 }, { two: 2 }));

    globalThis.CAIRN_FRONTEND_ENV = 'production';
    const originalError = console.error;
    console.error = () => {};
    try {
      assert.doesNotThrow(() => createAppState({ one: 1 }, { one: 2 }));
    } finally {
      console.error = originalError;
    }
  `);
}

function checkCairnAppStateHasNoDuplicateKeys() {
  runModuleAssertion(`
    import { createAppState } from './src/cairn/server/static/js/app/create-app-state.js';
    import { createCoreState } from './src/cairn/server/static/js/app/state-core.js';
    import { createSettingsState } from './src/cairn/server/static/js/app/state-settings.js';
    import { createSettingsAdminState } from './src/cairn/server/static/js/app/state-settings-admin.js';
    import { createPromptsState } from './src/cairn/server/static/js/app/state-prompts.js';
    import { createAiProfilesState } from './src/cairn/server/static/js/app/state-ai-profiles.js';
    import { createProxiesState } from './src/cairn/server/static/js/app/state-proxies.js';
    import { createWorkspaceUiState } from './src/cairn/server/static/js/workspace/state-ui.js';
    import { createWorkspaceGraphState } from './src/cairn/server/static/js/workspace/state-graph.js';
    import { createWorkspaceLogState } from './src/cairn/server/static/js/workspace/state-llm-log.js';
    import { createWorkspaceProjectsState } from './src/cairn/server/static/js/workspace/state-projects.js';
    import { createWorkspaceCapabilitiesState } from './src/cairn/server/static/js/workspace/state-capabilities.js';
    import { createWorkspaceCloakState } from './src/cairn/server/static/js/workspace/state-cloak.js';

    globalThis.CAIRN_FRONTEND_ENV = 'development';
    createAppState(
      createCoreState(),
      createWorkspaceGraphState(),
      createWorkspaceLogState(),
      createWorkspaceProjectsState(),
      createWorkspaceCloakState(),
      createSettingsState(),
      createSettingsAdminState(),
      createPromptsState(),
      createAiProfilesState(),
      createProxiesState(),
      createWorkspaceCapabilitiesState(),
      createWorkspaceUiState(),
    );
  `);
}

function checkWorkspaceLogShape() {
  runModuleAssertion(`
    import assert from 'node:assert/strict';
    import { createWorkspaceLogState } from './src/cairn/server/static/js/workspace/state-llm-log.js';

    const state = createWorkspaceLogState();
    const requiredKeys = [
      'ALL_LLM_EXECUTIONS_VALUE',
      'resetLlmState',
      'loadLlmExecutions',
      'loadLatestLlmEvents',
      'loadLlmEventPage',
      'filteredLlmEvents',
      'parseLlmEventContent',
      'openReplayConfig',
      'timelineViewModel',
    ];
    for (const key of requiredKeys) {
      assert.ok(key in state, 'missing LLM log state key: ' + key);
    }
    assert.equal(state.llmSelectedExecutionId, state.ALL_LLM_EXECUTIONS_VALUE);
  `);
}

function checkWorkspaceLogPaginationHelpers() {
  runModuleAssertion(`
    import assert from 'node:assert/strict';
    import {
      createWorkspaceLogEventState,
      llmBackendKindsForFilter,
      llmPageWindow,
      nextLlmPageCursor,
    } from './src/cairn/server/static/js/workspace/llm-log/events.js';

    const visible = ['prompt', 'stdout', 'stderr', 'tool_call', 'tool_result', 'command_start', 'command_end', 'error'];

    assert.deepEqual(
      llmBackendKindsForFilter('tools', visible),
      ['tool_call', 'tool_result', 'command_start', 'command_end'],
    );
    assert.deepEqual(
      llmBackendKindsForFilter('commands', visible),
      ['tool_call', 'tool_result', 'command_start', 'command_end'],
    );
    assert.deepEqual(llmBackendKindsForFilter('errors', visible), ['error']);
    assert.deepEqual(llmBackendKindsForFilter('output', visible), ['stdout', 'stderr', 'prompt']);
    assert.deepEqual(llmBackendKindsForFilter('tools', ['tool_call']), ['tool_call']);

    const page = llmPageWindow([{ sequence: 10 }, { sequence: 11 }, { sequence: 12 }], 2);
    assert.deepEqual(page.rows.map(row => row.sequence), [10, 11]);
    assert.equal(page.hasNext, true);

    const lastPage = llmPageWindow([{ sequence: 20 }], 2);
    assert.deepEqual(lastPage.rows.map(row => row.sequence), [20]);
    assert.equal(lastPage.hasNext, false);

    assert.equal(nextLlmPageCursor([{ sequence: 12 }, { sequence: 31 }]), 31);
    assert.equal(nextLlmPageCursor([]), 0);

    const state = createWorkspaceLogEventState();
    const latestRows = [
      { sequence: 1, event_kind: 'prompt' },
      { sequence: 2, event_kind: 'usage' },
      { sequence: 3, event_kind: 'system_event' },
      { sequence: 4, event_kind: 'tool_call' },
    ];
    assert.deepEqual(
      state.filterLatestLlmPreviewRows(latestRows).map(event => event.sequence),
      [1, 4],
    );

    const source = state.loadLatestLlmEvents.toString();
    assert.match(source, /filterLatestLlmPreviewRows\\(rows\\)/);
    assert.match(source, /mergeLlmCommandEvents\\(this\\.filterLatestLlmPreviewRows\\(rows\\)\\)/);
    assert.match(source, /\\.slice\\(0, 3\\)/);
    assert.equal(
      source.includes('includeEventKinds: false'),
      false,
      'latest LLM preview must use the visible event-kind allowlist',
    );
  `);
}

function checkExecutionLogUiNoLegacyHistoryMode() {
  const html = readFileSync(resolve(ROOT, 'src/cairn/server/partials/view_graph.html'), 'utf8');
  for (const legacyText of ['Open full log', 'Load history', 'Reload history', 'Show more events', 'Back to graph']) {
    assert.equal(html.includes(legacyText), false, `legacy execution log text remains: ${legacyText}`);
  }
  for (const legacyCode of [
    "graphMode === 'log'",
    "graphMode = 'log'",
    'handleLlmHistoryClick',
    'llmHistoryButtonLabel',
    'showMoreLlmEvents',
    'selectExecutionLog',
  ]) {
    assert.equal(html.includes(legacyCode), false, `legacy execution log UI path remains: ${legacyCode}`);
  }
}

function checkCapabilitySelectionHelpers() {
  runModuleAssertion(`
    import assert from 'node:assert/strict';
    import {
      sanitizeUserSkillIdsForProjectPayload,
      selectedCapabilitiesForPayload,
    } from './src/cairn/server/static/js/shared/capability-selection.js';

    assert.deepEqual(
      sanitizeUserSkillIdsForProjectPayload(['cypher-ctf', 'custom'], ['cypher-ctf']),
      ['custom'],
    );

    const payload = selectedCapabilitiesForPayload(
      {
        bootstrap: {
          user_mcp_server_ids: ['mcp-a'],
          user_skill_ids: ['cypher-ctf', 'custom-bootstrap'],
        },
        reason: {
          mcp_server_ids: ['mcp-fallback'],
          user_skill_ids: ['custom-reason'],
        },
      },
      [{ key: 'bootstrap' }, { key: 'reason' }],
      () => ({ mcp_server_ids: [], skill_ids: [] }),
      ['cypher-ctf'],
    );

    assert.deepEqual(payload, {
      bootstrap: {
        mcp_server_ids: ['mcp-a'],
        skill_ids: ['custom-bootstrap'],
      },
      reason: {
        mcp_server_ids: ['mcp-fallback'],
        skill_ids: ['custom-reason'],
      },
    });
  `);
}

function checkReadOnlyProjectCapabilityHelpers() {
  runModuleAssertion(`
    import assert from 'node:assert/strict';
    import { createWorkspaceCapabilitiesState } from './src/cairn/server/static/js/workspace/state-capabilities.js';

    const state = createWorkspaceCapabilitiesState();
    state.task_types = ['bootstrap'];
    state.taskTypeLabel = value => value;
    state.capabilities = {
      catalog: [
        { id: 'mcp-a', kind: 'mcp_server', name: 'Snapshot MCP', task_types: ['bootstrap'] },
        { id: 'skill-a', kind: 'skill', name: 'Snapshot Skill', task_types: ['bootstrap'] },
        { id: 'skill-extra', kind: 'skill', name: 'Unselected Skill', task_types: ['bootstrap'] },
      ],
      tasks: {
        bootstrap: {
          mcp_server_ids: ['mcp-a', 'mcp-missing'],
          skill_ids: ['skill-a'],
          user_mcp_server_ids: [],
          user_skill_ids: [],
        },
      },
      health: {},
      unavailable: { mcp_server_ids: ['mcp-missing'], skill_ids: [] },
    };

    assert.deepEqual(
      state.enabledCapabilitiesForTask('bootstrap', 'mcp_server').map(item => [item.id, item.name]),
      [['mcp-a', 'Snapshot MCP'], ['mcp-missing', 'mcp-missing']],
    );
    assert.deepEqual(
      state.enabledCapabilitiesForTask('bootstrap', 'skill').map(item => item.id),
      ['skill-a'],
    );
    assert.equal(
      state.enabledCapabilitiesForTask('bootstrap', 'skill').some(item => item.id === 'skill-extra'),
      false,
    );
  `);
}

function checkNewProjectDefaultCairnResourcesSelection() {
  runModuleAssertion(`
    import assert from 'node:assert/strict';
    import { createWorkspaceCapabilitiesState } from './src/cairn/server/static/js/workspace/state-capabilities.js';

    const state = createWorkspaceCapabilitiesState();
    state.task_types = ['bootstrap', 'explore', 'reason'];
    state.taskTypeLabel = value => value;
    state.roleDefaultTopLevelSkillIds = () => [];
    state.newProjectCatalog = {
      capabilities: [
        { id: 'cairn-resources', kind: 'mcp_server', name: 'Cairn Resources MCP', task_types: ['bootstrap', 'explore'], available: true },
      ],
    };
    state.newProject = { capabilities: state.defaultTaskCapabilitiesMap() };
    state.applyDefaultNewProjectCapabilities();

    assert.deepEqual(state.newProject.capabilities.bootstrap.user_mcp_server_ids, ['cairn-resources']);
    assert.deepEqual(state.newProject.capabilities.explore.user_mcp_server_ids, ['cairn-resources']);
    assert.deepEqual(state.newProject.capabilities.reason.user_mcp_server_ids, []);
    assert.deepEqual(state.selectedCapabilitiesForPayload(state.newProject.capabilities), {
      bootstrap: { mcp_server_ids: ['cairn-resources'], skill_ids: [] },
      explore: { mcp_server_ids: ['cairn-resources'], skill_ids: [] },
      reason: { mcp_server_ids: [], skill_ids: [] },
    });
    assert.equal(state.cairnResourcesDefaultStatus().ok, true);
    assert.match(state.cairnResourcesDefaultStatus().message, /Servers\\/Project Proxy discovery depends on Cairn Resources MCP/);

    state.newProjectCatalog.capabilities[0].available = false;
    state.newProject = { capabilities: state.defaultTaskCapabilitiesMap() };
    state.applyDefaultNewProjectCapabilities();
    assert.deepEqual(state.newProject.capabilities.bootstrap.user_mcp_server_ids, []);
    assert.equal(state.cairnResourcesDefaultStatus().ok, false);

    state.newProjectCatalog.capabilities = [];
    assert.match(state.cairnResourcesDefaultStatus().label, /unavailable/);
  `);
}

function checkProjectCairnResourcesAuditWarning() {
  runModuleAssertion(`
    import assert from 'node:assert/strict';
    import { createWorkspaceCapabilitiesState } from './src/cairn/server/static/js/workspace/state-capabilities.js';

    const state = createWorkspaceCapabilitiesState();
    state.capabilities = {
      audit: {
        tasks: {
          bootstrap: { has_cairn_resources: false },
          explore: { has_cairn_resources: true },
          reason: { has_cairn_resources: false },
        },
      },
    };
    assert.match(state.projectCairnResourcesAuditWarning(), /missing cairn-resources for bootstrap/);

    state.capabilities.audit.tasks.bootstrap.has_cairn_resources = true;
    assert.equal(state.projectCairnResourcesAuditWarning(), '');
  `);
}

function checkFormHelpers() {
  runModuleAssertion(`
    import assert from 'node:assert/strict';
    import {
      jsonObjectToText,
      keyValueObjectToText,
      normalizeStringList,
      textToJsonObject,
      textToKeyValueObject,
    } from './src/cairn/server/static/js/shared/form.js';

    assert.deepEqual(normalizeStringList('one, two\\nthree'), ['one', 'two', 'three']);
    assert.deepEqual(textToKeyValueObject('A=1\\nB = two=three'), { A: '1', B: 'two=three' });
    assert.equal(keyValueObjectToText({ A: '1', B: 'two' }), 'A=1\\nB=two');
    assert.deepEqual(textToJsonObject('{ "timeout": 2 }'), { timeout: 2 });
    assert.equal(jsonObjectToText(['not-object']), '{}');
    assert.throws(() => textToKeyValueObject('missing_equals'), /Invalid key=value line/);
    assert.throws(() => textToJsonObject('[]'), /Probe config must be a JSON object/);
  `);
}

function checkPrefHelpers() {
  runModuleAssertion(`
    import assert from 'node:assert/strict';
    import {
      isFiniteNumber,
      parseNumberPref,
      readPref,
      writePref,
    } from './src/cairn/server/static/js/shared/prefs.js';

    const store = new Map();
    globalThis.localStorage = {
      getItem(key) {
        return store.has(key) ? store.get(key) : null;
      },
      setItem(key, value) {
        store.set(key, value);
      },
    };

    assert.equal(readPref('missing', 42), 42);
    writePref('width', 320);
    assert.equal(readPref('width', 0, { parse: parseNumberPref, validate: isFiniteNumber }), 320);
    writePref('width', 'not-a-number');
    assert.equal(readPref('width', 260, { parse: parseNumberPref, validate: isFiniteNumber }), 260);
  `);
}

function checkApiClientHelpers() {
  runModuleAssertion(`
    import assert from 'node:assert/strict';
    import { createApiClient } from './src/cairn/server/static/js/shared/api-client.js';

    let token = 'old-token';
    const calls = [];
    const jsonResponse = (status, body) => ({
      status,
      ok: status >= 200 && status < 300,
      json: async () => body,
    });
    const client = createApiClient({
      getToken: () => token,
      setToken: value => {
        token = value;
      },
      clearToken: () => {
        token = '';
      },
      fetchImpl: async (path, opts = {}) => {
        calls.push({ path, opts });
        if (path === '/auth/refresh') return jsonResponse(200, { access_token: 'new-token' });
        if (path === '/needs-refresh' && opts.headers?.Authorization === 'Bearer old-token') {
          return jsonResponse(401, { detail: 'expired' });
        }
        return jsonResponse(200, { ok: true, auth: opts.headers?.Authorization || '' });
      },
    });

    const data = await client.api('GET', '/needs-refresh');
    assert.equal(token, 'new-token');
    assert.equal(data.auth, 'Bearer new-token');
    assert.deepEqual(calls.map(call => call.path), ['/needs-refresh', '/auth/refresh', '/needs-refresh']);
  `);
}

function runModuleAssertion(source) {
  execFileSync(
    process.execPath,
    ['--input-type=module', '-e', source],
    { cwd: ROOT, stdio: 'pipe' },
  );
}

function main() {
  assert.ok(statSync(JS_ROOT).isDirectory(), `missing JS root: ${JS_ROOT}`);
  const files = walkJsFiles(JS_ROOT);
  checkSyntax(files);
  checkLocalImportsResolve(files);
  checkStateFileSizes(files);
  checkNoDuplicateKeys();
  checkCairnAppStateHasNoDuplicateKeys();
  checkWorkspaceLogShape();
  checkWorkspaceLogPaginationHelpers();
  checkExecutionLogUiNoLegacyHistoryMode();
  checkCapabilitySelectionHelpers();
checkReadOnlyProjectCapabilityHelpers();
checkNewProjectDefaultCairnResourcesSelection();
checkProjectCairnResourcesAuditWarning();
checkFormHelpers();
  checkPrefHelpers();
  checkApiClientHelpers();
}

main();
