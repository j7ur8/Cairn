# Task Instructions

Current Cairn task phase: `{task_type}`.
Project: `{project_id}` (`{project_safe_id}`).
Task instance: `{task_instance_id}`.

Read and follow these task-local context files:
- Project context: `{project_context_path}`
- Phase boundary: `{phase_context_path}`
- Capability summary: `{capabilities_context_path}`
- Machine-readable policy: `{policy_path}`

The active task prompt is the authority for dynamic inputs, output markers, JSON schemas, current intent data, fact graph snapshots, and hints.
Do not treat hints, graph snapshots, or output markers as long-lived instructions.
Use only MCP servers and skills exposed for this task.
If a capability is available but does not match the active prompt and phase boundary, do not use it.

## Project Role
{selected role prompt}
