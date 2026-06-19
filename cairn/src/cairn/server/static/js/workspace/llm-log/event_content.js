export function createWorkspaceLogEventContentState() {
  return {
    llmExecutionOptionLabel(execution) {
      const stamp = this.formatExecutionStamp(execution.started_at) || '--:--';
      const taskType = execution.task_type || '';
      const intent = execution.intent_id ? ` · ${execution.intent_id}` : '';
      const state = execution.process_state || '';
      const events = Number(execution.event_count || 0);
      const eventText = `${events} events`;

      let taskPadding = '';
      if (taskType === 'reason') taskPadding = '   ';
      else if (taskType === 'explore') taskPadding = '  ';
      // bootstrap => no extra task padding

      const missingIntentPadding = execution.intent_id ? '' : '    ';

      return `${stamp}  ${taskType}${taskPadding}${intent}${missingIntentPadding}  ${state}  ${eventText}`;
    },

    llmEventContentMode(event) {
      return this.parseLlmEventContent(event).mode;
    },

    llmEventParsedCard(event) {
      return this.parseLlmEventContent(event).card || null;
    },

    llmEventParsedCards(event) {
      return this.parseLlmEventContent(event).cards || [];
    },

    parseLlmEventContent(event) {
      // Cheap cache key: events are immutable after insert, and merged
      // events expose their parsed payload directly. Skips the O(content)
      // key construction the old implementation did on every render.
      const cacheKey = `${event.sequence}:${event._merged_call ? 1 : 0}`;
      const cached = this.llmEventContentCache[cacheKey];
      if (cached) return cached;

      // Fast path: merged events have _parsedPayload attached at build time.
      if (event._parsedPayload) {
        const value = {
          mode: 'json_card',
          card: this.buildLlmJsonCard(event, event._parsedPayload),
          cards: [],
        };
        this.llmEventContentCache[cacheKey] = value;
        return value;
      }

      const parsedObject = this._getParsedPayload(event);
      let value;
      if (parsedObject) {
        value = {
          mode: 'json_card',
          card: this.buildLlmJsonCard(event, parsedObject),
          cards: [],
        };
      } else {
        const raw = typeof event.content === 'string' ? event.content : String(event.content || '');
        const parsedLines = this.tryParseLlmJsonLines(raw);
        if (parsedLines.length > 1) {
          value = {
            mode: 'json_lines',
            card: null,
            cards: parsedLines.map((payload, index) => this.buildLlmJsonCard(event, payload, index)),
          };
        } else {
          value = { mode: 'plain_text', card: null, cards: [] };
        }
      }
      this.llmEventContentCache[cacheKey] = value;
      return value;
    },

    tryParseLlmJsonObject(raw) {
      const text = (raw || '').trim();
      if (!text.startsWith('{') || !text.endsWith('}')) return null;
      try {
        const parsed = JSON.parse(text);
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
      } catch {
        return null;
      }
    },

    tryParseLlmJsonLines(raw) {
      const lines = (raw || '')
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean);
      if (lines.length <= 1) return [];
      const parsed = [];
      for (const line of lines) {
        try {
          const value = JSON.parse(line);
          if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
          parsed.push(value);
        } catch {
          return [];
        }
      }
      return parsed;
    },

    buildLlmJsonCard(event, payload, index = 0) {
      const summary = this.deriveLlmPayloadSummary(event, payload, index);
      const inlineFields = [];
      const blockFields = [];
      const used = new Set();

      const addInline = (key, label, value) => {
        if (value === undefined || value === null || value === '') return;
        inlineFields.push({ label, value: this.llmFieldText(key, value) });
        used.add(key);
      };
      const addBlock = (key, label, value) => {
        if (value === undefined || value === null || value === '') return;
        blockFields.push({ label, value: this.llmFieldText(key, value) });
        used.add(key);
      };

      if (event.event_kind === 'tool_call') {
        addInline('tool', 'Tool', payload.tool);
        addInline('call_id', 'Call ID', payload.call_id);
        addBlock('arguments', 'Arguments', payload.arguments);
      } else if (event.event_kind === 'tool_result') {
        addInline('call_id', 'Call ID', payload.call_id);
        addInline('is_error', 'Is Error', payload.is_error);
        addBlock('output', 'Output', payload.output);
      } else if (event.event_kind === 'command_start') {
        addInline('call_id', 'Call ID', payload.call_id);
        addInline('workdir', 'Workdir', payload.workdir || payload.cwd);
        addInline('description', 'Description', payload.description);
        addBlock('command', 'Command', payload.command);
      } else if (event.event_kind === 'command_end') {
        addInline('call_id', 'Call ID', payload.call_id);
        addInline('status', 'Status', payload.status);
        addInline('exit_code', 'Exit Code', payload.exit_code);
        addInline('interrupted', 'Interrupted', payload.interrupted);
        addInline('cwd', 'CWD', payload.cwd || payload.workdir);
        addBlock('command', 'Command', payload.command);
        addBlock('stdout', 'Stdout', payload.stdout);
        addBlock('stderr', 'Stderr', payload.stderr);
        addBlock('output', 'Output', payload.output);
        addBlock('duration', 'Duration', payload.duration);
        // Merged CALL cards surface `description` as the row-1 title via
        // llmEventHeaderText. Mark it used here so the trailing fallback
        // loop does not render a duplicate Description inline field.
        if (payload.description !== undefined && payload.description !== null && payload.description !== '') {
          used.add('description');
        }
      } else if (event.event_kind === 'usage') {
        for (const key of ['type', 'subtype', 'input_tokens', 'output_tokens', 'thinking_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'service_tier', 'model']) {
          if (Object.prototype.hasOwnProperty.call(payload, key)) addInline(key, this.llmFieldLabel(key), payload[key]);
        }
      } else if (event.event_kind === 'session_init') {
        for (const key of ['model', 'cwd', 'session_id', 'permissionMode', 'apiKeySource', 'claude_code_version', 'output_style']) {
          if (Object.prototype.hasOwnProperty.call(payload, key)) addInline(key, this.llmFieldLabel(key), payload[key]);
        }
        for (const key of ['tools', 'mcp_servers', 'slash_commands', 'agents', 'skills', 'plugins']) {
          if (Object.prototype.hasOwnProperty.call(payload, key)) addBlock(key, this.llmFieldLabel(key), payload[key]);
        }
      } else if (event.event_kind === 'api_retry') {
        for (const key of ['attempt', 'max_retries', 'retry_delay_ms', 'error_status', 'error', 'session_id']) {
          if (Object.prototype.hasOwnProperty.call(payload, key)) addInline(key, this.llmFieldLabel(key), payload[key]);
        }
      } else if (event.event_kind === 'capability_manifest') {
        for (const key of ['project_id', 'task_type']) {
          if (Object.prototype.hasOwnProperty.call(payload, key)) addInline(key, this.llmFieldLabel(key), payload[key]);
        }
        for (const key of ['mcp_servers', 'skills', 'unavailable']) {
          if (Object.prototype.hasOwnProperty.call(payload, key)) addBlock(key, this.llmFieldLabel(key), payload[key]);
        }
      } else if (event.event_kind === 'system_event') {
        for (const key of ['type', 'subtype', 'session_id']) {
          if (Object.prototype.hasOwnProperty.call(payload, key)) addInline(key, this.llmFieldLabel(key), payload[key]);
        }
      } else if (event.event_kind === 'trace_parse_error') {
        addBlock('line_preview', 'Line Preview', payload.line_preview);
      }

      for (const [key, value] of Object.entries(payload)) {
        if (key === 'summary' || used.has(key)) continue;
        if (this.llmFieldShouldUseBlock(key, value)) addBlock(key, this.llmFieldLabel(key), value);
        else addInline(key, this.llmFieldLabel(key), value);
      }

      return { summary, inlineFields, blockFields };
    },

    deriveLlmPayloadSummary(event, payload, index = 0) {
      if (typeof payload.summary === 'string' && payload.summary.trim()) return payload.summary.trim();
      if (typeof payload.subtype === 'string' && typeof payload.type === 'string') return `${payload.type}: ${payload.subtype}`;
      if (typeof payload.type === 'string' && typeof payload.role === 'string') return `${payload.type}: ${payload.role}`;
      if (typeof payload.type === 'string' && payload.type) return payload.type;
      if (payload.message && typeof payload.message === 'object') {
        const role = payload.message.role;
        if (typeof role === 'string' && role) return `message: ${role}`;
      }
      if (event.event_kind === 'tool_call' && payload.tool) return `${payload.tool}`;
      if (event.event_kind === 'command_start' || event.event_kind === 'command_end') {
        const commandText = this.llmFieldText('command', payload.command || payload.summary || '');
        if (commandText) return commandText;
      }
      return `${this.llmEventLabel(event)} ${index > 0 ? `#${index + 1}` : ''}`.trim();
    },

    llmFieldShouldUseBlock(key, value) {
      if (['arguments', 'output', 'stdout', 'stderr', 'line_preview', 'content', 'message', 'toolUseResult', 'tools', 'mcp_servers', 'slash_commands', 'agents', 'skills', 'plugins', 'command', 'duration'].includes(key)) return true;
      if (Array.isArray(value)) return true;
      if (value && typeof value === 'object') return true;
      if (typeof value === 'string' && value.length > 160) return true;
      return false;
    },

    llmFieldLabel(key) {
      const labels = {
        call_id: 'Call ID',
        cwd: 'CWD',
        workdir: 'Workdir',
        stdout: 'Stdout',
        stderr: 'Stderr',
        input_tokens: 'Input Tokens',
        output_tokens: 'Output Tokens',
        thinking_tokens: 'Thinking Tokens',
        cache_creation_input_tokens: 'Cache Creation Input Tokens',
        cache_read_input_tokens: 'Cache Read Input Tokens',
        exit_code: 'Exit Code',
        session_id: 'Session ID',
        mcp_servers: 'MCP Servers',
        slash_commands: 'Slash Commands',
        permissionMode: 'Permission Mode',
        apiKeySource: 'API Key Source',
        project_id: 'Project ID',
        task_type: 'Task Type',
        unavailable: 'Unavailable',
      };
      if (labels[key]) return labels[key];
      return key
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, char => char.toUpperCase());
    },

    llmEventKindLabel(kind) {
      return this.llmFieldLabel(kind);
    },

    llmFieldText(key, value) {
      if (value === undefined || value === null) return '';
      if (typeof value === 'boolean') return value ? 'true' : 'false';
      if (Array.isArray(value)) {
        if (key === 'command' && value.every(item => typeof item === 'string' || typeof item === 'number')) {
          return value.map(item => String(item)).join(' ');
        }
        return JSON.stringify(value, null, 2);
      }
      if (typeof value === 'object') return JSON.stringify(value, null, 2);
      return String(value);
    },

    // For CALL cards, the merged payload's description becomes the row-1
    // title and task_type / worker / phase collapse into row 2. Other
    // events keep the original task_type · worker / phase split.
    _llmEventHasDescription(event) {
      if (!event || !event._merged_call) return false;
      const desc = event._parsedPayload && event._parsedPayload.description;
      return typeof desc === 'string' ? desc.trim().length > 0 : !!desc;
    },

    _llmEventDescriptionText(event) {
      const desc = event._parsedPayload && event._parsedPayload.description;
      return typeof desc === 'string' ? desc.trim() : String(desc);
    },

    llmEventHeaderText(event) {
      // CALL cards with a description show it as the title; everything else
      // has no title text in row 1 (just badge + #sequence + time).
      return this._llmEventHasDescription(event)
        ? this._llmEventDescriptionText(event)
        : '';
    },

    llmEventHeaderTitle(event) {
      return this._llmEventHasDescription(event)
        ? this._llmEventDescriptionText(event)
        : '';
    },

    llmEventSubHeaderText(event) {
      if (this._llmEventHasDescription(event)) {
        const parts = [event.task_type, event.worker, event.phase].filter(
          (part) => part !== undefined && part !== null && String(part).length > 0,
        );
        return parts.join(' · ');
      }
      return event.phase || '';
    },

    llmEventLabel(event) {
      if (event._merged_call) return 'Call';
      if (event._merged_command) return 'Command';
      const labels = {
        prompt: 'Prompt',
        stdout: 'Stdout',
        stderr: 'Stderr',
        model_response: 'Result',
        parse_error: 'Parse Error',
        timeout: 'Timeout',
        cancelled: 'Cancelled',
        process_end: 'Process End',
        error: 'Error',
        result: 'Result',
        agent_message: 'Agent',
        thinking: 'Thinking',
        tool_call: 'Tool Call',
        tool_result: 'Tool Result',
        command_start: 'Command Start',
        command_end: 'Command End',
        usage: 'Usage',
        session_init: 'Session Init',
        api_retry: 'API Retry',
        system_event: 'System',
        capability_manifest: 'Capabilities',
        trace_parse_error: 'Trace Parse',
      };
      return labels[event.event_kind] || event.event_kind || 'Event';
    },

    llmEventBadgeClass(event) {
      if (event._merged_call) return 'bg-sky-50 text-sky-700';
      const kind = event.event_kind;
      if (kind === 'prompt') return 'bg-violet-50 text-violet-700';
      if (kind === 'stdout') return 'bg-slate-100 text-slate-700';
      if (kind === 'stderr') return 'bg-amber-50 text-amber-700';
      if (kind === 'model_response' || kind === 'result') return 'bg-teal-50 text-teal-700';
      if (kind === 'agent_message') return 'bg-teal-50 text-teal-700';
      if (kind === 'thinking') return 'bg-indigo-50 text-indigo-700';
      if (kind === 'tool_call' || kind === 'tool_result') return 'bg-sky-50 text-sky-700';
      if (kind === 'command_start' || kind === 'command_end') return 'bg-slate-100 text-slate-700';
      if (kind === 'usage') return 'bg-emerald-50 text-emerald-700';
      if (kind === 'capability_manifest') return 'bg-cyan-50 text-cyan-700';
      if (['session_init', 'api_retry', 'system_event'].includes(kind)) return 'bg-slate-100 text-slate-700';
      if (['parse_error', 'trace_parse_error', 'timeout', 'cancelled', 'error'].includes(kind)) return 'bg-rose-50 text-rose-700';
      return 'bg-sky-50 text-sky-700';
    },

    llmEventBorderClass(event) {
      if (event._merged_call) return 'border-sky-200';
      if (['parse_error', 'trace_parse_error', 'timeout', 'cancelled', 'error'].includes(event.event_kind)) return 'border-rose-200';
      if (event.event_kind === 'stderr') return 'border-amber-200';
      if (event.event_kind === 'capability_manifest') return 'border-cyan-200';
      if (['tool_call', 'tool_result'].includes(event.event_kind)) return 'border-sky-200';
      if (['command_start', 'command_end'].includes(event.event_kind)) return 'border-slate-300';
      return 'border-slate-200';
    },

    llmEventExpanded(event) {
      // Every card is collapsed by default; only explicit user toggles open it.
      return !!this.llmExpandedEvents[event.sequence];
    },

    toggleLlmEvent(sequence) {
      const event = this.llmEvents.find(item => item.sequence === sequence) || { sequence, event_kind: 'manual' };
      this.llmExpandedEvents[sequence] = !this.llmEventExpanded(event);
    },

    toggleLlmPolling() {
      this.llmPollingPaused = !this.llmPollingPaused;
      if (!this.llmPollingPaused) this.pollLlmEvents(true);
    },

    collapseLlmPanel() {
      this.llmPanelCollapsed = true;
      this.saveLlmPanelPrefs();
      this.settleGraphViewport();
    },

    expandLlmPanel() {
      this.llmPanelCollapsed = false;
      this.saveLlmPanelPrefs();
      this.pollLlmEvents(true);
      this.resetLlmEventPagination();
      this.settleGraphViewport();
    },
  };
}
