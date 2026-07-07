# Task
You will receive a compact YAML view of the task graph and a full graph YAML fallback. In the YAML graph, facts represent key objective facts, and intents represent exploration intents. The graph always moves from one or more facts to a new fact by proposing an intent for exploration. Interpret the graph information and the assigned Current Intent in the context of the task-local project instructions.
You will also be assigned a specific `Current Intent`. You only need to explore in the direction of this specific Intent and try to advance the task toward the goal described by Goal.

## Output Requirements
Return only the confirmed incremental fact as plain text wrapped between the exact sentinel marker below. Do not output JSON, markdown fences, explanations, or text outside the marker pair.

Normal return example:
32173462130721312360912confirmed incremental fact text32173462130721312360912

## Rules
- Explore only the Current Intent. Stop when evidence is sufficient, the path is disproven, or the active phase boundary is reached.
- Read the Fact View first. Read the Full Graph only if the view is insufficient or you need omitted details.
- The plain-text fact must clearly state the confirmed key objective results. For example, in a CTF scenario, it may include multiple flags, shells, privilege proofs, key exploitation results, and similar evidence. Do not put long data blobs in the fact; long data should be placed in a file and referenced from the fact instead.
- The fact should contain only the latest incremental facts discovered. Do not repeat information already present in the graph snapshot, and do not include redundant details that do not help advance Goal.
- When the result is negative or partial, state the tested method or scope, the concrete failure limit, and any adjacent sibling method or broader direction that remains untested or not excluded. Do not turn one method failure into a whole-family failure unless the evidence actually covers the whole family.
- When evidence still supports or weakens the broader direction after a partial result, say so plainly in the fact. This lets later reasoning separate a dead leaf from a still-valuable family.

## Context
### Hints
```
{hints}
```

### Fact View
```
{fact_view}
```

### Full Graph
```
{full_graph}
```

### Current Intent
```
{intent_id}
```

### Current Intent Description
```
{intent_description}
```
