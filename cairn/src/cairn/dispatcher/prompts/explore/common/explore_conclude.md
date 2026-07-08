Active prompt: explore_conclude.md

# Task

Explore_conclude summarizes already confirmed Explore results for the assigned Current Intent.

Use Fact View as confirmed context. Use Full Graph only as fallback when Fact View is insufficient. Use Current Intent and Current Intent Description to identify the assigned intent and requested exploration scope.

Do not collect new information. Summarize only confirmed Explore facts that are ready to add to the graph.

## Output Requirements
For a normal successful result, return only the confirmed Explore facts as plain text surrounded by 32173462130721312360912. Do not output JSON. Do not output anything outside the markers.

If you cannot produce a successful fact summary, output a plain error explanation without 32173462130721312360912.

Normal return example:
```text
32173462130721312360912Confirmed fact summary...32173462130721312360912
```

### Rules
- The marked text must contain only already confirmed objective factual conclusions. Do not output plans, guesses, next-step suggestions, or explanatory filler.
- Do not put long data blobs in the marked text. Long data should be placed in a file and referenced from the marked text instead.
- Include only the latest incremental facts discovered. Do not repeat information already present in the graph snapshot.
- When summarizing a negative or partial result, include the tested method or scope, the concrete failure limit, and any sibling direction that remains untested or not excluded. Do not summarize one failed method as a whole-family failure unless the confirmed evidence covers the whole family.
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
