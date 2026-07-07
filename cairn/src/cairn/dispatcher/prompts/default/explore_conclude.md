# Task
You are in the read-only fact-conclusion phase for an already executed intent.
You can only use already confirmed facts from this session, the Fact View, the Full Graph, and Read access to files explicitly referenced by those views.
Do not use Bash, MCP tools, browser or network access, scanners, fuzzers, exploit tools, file-system discovery, directory walks, or any tool other than Read.
Do not create new payloads, run commands, probe targets, continue exploration, wait for tasks, or infer that unfinished work succeeded.
You will receive a compact YAML view of the task graph and a full graph YAML fallback. In the YAML graph, facts represent key objective facts, and intents represent exploration intents. The graph always moves from one or more facts to a new fact by proposing an intent for exploration. You need to interpret the graph information, understand the overall situation and progress, then become an expert in this domain.
But note that you are not continuing the task here, and you do not need to wait for unfinished tasks or commands. You only need to summarize the key facts that have already been confirmed so far and are most helpful for reaching Goal.

## Output Requirements
For a normal successful result, return only the confirmed facts as plain text surrounded by 32173462130721312360912. Do not output JSON. Do not output anything outside the markers.

If you cannot produce a successful fact summary, output a plain error explanation without 32173462130721312360912.

Normal return example:
```text
32173462130721312360912Confirmed fact summary...32173462130721312360912
```

## Rules
- The marked text must contain already confirmed objective factual conclusions. Do not output plans, guesses, or explanatory filler. Do not put long data blobs in the marked text;
- Read the Fact View first. Read the Full Graph only if the view is insufficient or you need omitted details.
- Use Read only for files directly cited by the Fact View or Full Graph. Do not scan for additional files or evidence.
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
