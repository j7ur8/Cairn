# Task Instructions

Current Cairn task family: `{task_type}`.
Project: `{project_id}` (`{project_safe_id}`).
Task instance: `{task_instance_id}`.

The task prompt provides the task-specific graph state, valid fact ids, open intents, output markers, and JSON schemas.
Do not treat hints, graph snapshots, or output markers as long-lived instructions.
Use only MCP servers and skills exposed for this task.
If a capability is available but does not match the reason boundary, do not use it.

## Reason Session Rules
- Reason is a single-phase LLM session.
- Do not continue any previous bootstrap, bootstrap_conclude, explore, or explore_conclude work.
- Use only the current reason task prompt and the confirmed state it provides.

## Phase Boundary
- Reason does not execute tools or continue exploration.
- Judge whether the confirmed graph satisfies the goal, needs new intents, or should wait for existing open intents.
- Use only the graph, hints, fact ids, open intents, and output schema in the active prompt.

## Capability Summary
{selected_mcp_ids}

## Project Role
{selected role prompt}
