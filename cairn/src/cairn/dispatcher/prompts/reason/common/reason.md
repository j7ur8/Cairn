Active prompt: reason.md

# Task

Reason evaluates the confirmed graph and emits one protocol decision.

Use Fact View as the primary graph state. Use Full Graph only as fallback when Fact View is insufficient. Use Valid facts for allowed completion sources and Open Intents for already declared work.

Decide exactly one state: Goal satisfied, propose new high-value intents, or wait with no new intent.

Do not execute tools, collect new information, or continue exploration.

## Output Requirements
Return exactly one marker-wrapped JSON object. The marker chooses the reason state. Do not output markdown fences, explanations, or text outside the marker pair. The JSON inside the marker must be valid, including proper escaping of quotation marks.

If Goal has been satisfied, return:
32173462130721312360912
{"accepted": true, "data": {"complete": {"from": ["f001"], "description": "..."}}}
32173462130721312360912

If Goal has not been satisfied but new intents should be proposed, return:
84913462130721312360912
{"accepted": true, "data": {"intents": [{"from": ["f001"], "description": "..."}, {"from": ["f002", "f003"], "description": "..."}]}}
84913462130721312360912

If Goal has not been satisfied and no new intent should currently be proposed, return:
00003462130721312360912
{"accepted": true, "data": {}}
00003462130721312360912

### Rules
- Use only the confirmed graph state in Fact View and Full Graph. Do not infer from outside knowledge or collect fresh evidence.
- First determine whether the confirmed facts already satisfy Goal. If they do, `data.complete.from` must come only from `Valid facts`, and `data.complete.description` must explain why the currently confirmed results are sufficient.
- If Goal is not satisfied, decide whether the graph supports new intent directions or should wait for existing work.
- Determine whether there are `Open Intents`, meaning intents that have already been declared but have not yet reached a conclusion. If there are open intents, compare known clues in facts to infer whether the current intents already cover them and whether new intents are necessary.
- If `Open Intents` is empty, you must propose new intents.
- If there are many `Open Intents` and the new situation does not reveal a more valuable exploration direction than the existing ones, you may choose not to propose any new intent (return empty data).
- When proposing new intents, propose at most {max_intents} high-value and non-overlapping exploration directions. Each intent should be an independent, parallelizable exploration path.
- Each Intent should be a high-value exploration direction. It does not need to be overly detailed. Focus on the core insight and a clear direction. Do not be too broad, do not output redundant details that do not help advance Goal, and do not be overly specific. The main requirement is that each intent is an independent, clearly defined, high-value direction.
- An Intent may originate from multiple facts.
- Different intents should cover different exploration dimensions and avoid duplication or heavy overlap.

### Context
#### Fact View
```
{fact_view}
```

#### Full Graph
```
{full_graph}
```

#### Valid facts
```
{fact_ids}
```

#### Open Intents
```
{open_intents}
```
