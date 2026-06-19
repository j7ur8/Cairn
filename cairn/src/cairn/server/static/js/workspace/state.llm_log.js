import { createWorkspaceLogBaseActions } from './llm-log/base.js';
import { createWorkspaceLogEventContentState } from './llm-log/event_content.js';
import { createWorkspaceLogEventState } from './llm-log/events.js';
import { createWorkspaceLogReplayState } from './llm-log/replay.js';
import { createWorkspaceLogBaseState } from './llm-log/state.js';
import { createWorkspaceLogTimelineState } from './llm-log/timeline.js';

export function createWorkspaceLogState() {
  return {
    ...createWorkspaceLogBaseState(),
    ...createWorkspaceLogBaseActions(),
    ...createWorkspaceLogEventState(),
    ...createWorkspaceLogEventContentState(),
    ...createWorkspaceLogReplayState(),
    ...createWorkspaceLogTimelineState(),
  };
}
