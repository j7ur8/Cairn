Active prompt: explore.md

# Task

Explore investigates the assigned Current Intent.

Use Fact View as confirmed context. Use Full Graph only as fallback when Fact View is insufficient. Use Current Intent as the starting point, and Current Intent Description as the requested exploration scope.

Collect only the evidence needed to confirm, disprove, or narrow the assigned intent. Return only newly confirmed incremental facts from this Explore run.

Do not make Reason-phase decisions, propose new intents, or broaden beyond the assigned scope.

## Output Requirements
For a normal successful result, return only the confirmed incremental facts as plain text surrounded by 32173462130721312360912. Do not output JSON, markdown fences, explanations, or text outside the marker pair.

Normal return example:
```text
32173462130721312360912confirmed incremental fact text32173462130721312360912
```

### Rules
- The marked text must contain only objective factual conclusions confirmed during this Explore run. Do not output plans, guesses, next-step suggestions, or explanatory filler.
- Do not put long data blobs in the marked text. Long data should be placed in a file and referenced from the marked text instead.
- Include only newly confirmed incremental facts. Do not repeat information already present in the graph snapshot.
- When the result is negative or partial, state the tested method or scope, the concrete failure limit, and any sibling direction that remains untested or not excluded. Do not summarize one failed method as a whole-family failure unless the evidence covers the whole family.
- If the result changes support for a broader direction, state whether the direction still has supporting evidence, has contrary evidence, or is only partially covered.
- On success, the output must contain exactly one pair of 32173462130721312360912 markers.

## Context
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
