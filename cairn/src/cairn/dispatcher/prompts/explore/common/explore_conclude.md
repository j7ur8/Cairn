Active prompt: explore_conclude.md

# Task
You will receive a compact YAML view of the task graph and a full graph YAML fallback. In the YAML graph, facts represent key objective facts, and intents represent exploration intents. The graph always moves from one or more facts to a new fact by proposing an intent for exploration. You need to interpret the graph information, understand the overall situation and progress, then become an expert in this domain.

Summarize the key facts that have already been confirmed so far and are most helpful for reaching Goal.

## Output Requirements
For a normal successful result, return only the confirmed facts as plain text surrounded by 32173462130721312360912. Do not output JSON. Do not output anything outside the markers.

If you cannot produce a successful fact summary, output a plain error explanation without 32173462130721312360912.

Normal return example:
```text
32173462130721312360912Confirmed fact summary...32173462130721312360912
```

### Rules
- The marked text must contain already confirmed objective factual conclusions. Do not output plans, guesses, or explanatory filler. Do not put long data blobs in the marked text;
- The marked text should contain only the latest incremental facts discovered. Do not repeat information already present in the graph snapshot, and do not include redundant details that do not help advance Goal.
- When summarizing a negative or partial result, include the tested method or scope, the concrete failure limit, and any adjacent sibling method or broader direction that remains untested or not excluded. Do not summarize one failed method as a whole-family failure unless the confirmed evidence covers the whole family.
- If the result changes support for the broader direction, state whether it still has supporting evidence, has contrary evidence, or is only partially covered.
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
