# Task Instructions

Current Cairn task family: `{task_type}`.
Project: `{project_id}` (`{project_safe_id}`).
Task instance: `{task_instance_id}`.

The task prompt provides the task-specific graph state, valid fact ids, open intents, output markers, and JSON schemas.
Do not treat graph snapshots or output markers as long-lived instructions.
Use only MCP servers and skills exposed for this task.
If a capability is available but does not match the reason boundary, do not use it.

## Reason Session Rules
- Reason is a single-phase LLM session.
- Do not continue any previous bootstrap, bootstrap_conclude, explore, or explore_conclude work.
- Reason evaluates the confirmed graph and emits one protocol decision.

## Phase Boundary
- Reason does not execute tools, collect new information, or continue any prior phase.
- Judge whether the confirmed graph satisfies the goal, needs new intents, or should wait for existing open intents.
- Use only the graph, fact ids, open intents, and output schema in the active prompt.

## Capability Summary
{selected_mcp_ids}

## Project Role
{selected role prompt}
