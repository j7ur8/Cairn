# Task

Follow the task-local phase boundary referenced by CLAUDE.md/AGENTS.md. Bootstrap is target discovery and profiling only; vulnerability verification and exploitation belong in later Explore intents created by Reason.

Build a concise target profile from static, provided, and publicly observable facts about the Origin, target identity, purpose, exposed entrypoints or artifacts, technology and runtime fingerprints, access boundaries, supplied materials, linked public resources, constraints, and directly observable abnormal behavior.

## Output Requirements
For a normal successful result, return only the confirmed target profile facts as plain text surrounded by 32173462130721312360912. Do not output anything outside the markers.

If you cannot produce confirmed target profile facts, output a plain error explanation without 32173462130721312360912.

Normal return example:
```text
32173462130721312360912Confirmed target profile facts...32173462130721312360912
```

## Rules
- The marked text must contain only objective factual conclusions confirmed during this bootstrap run. Do not output plans, guesses, next-step suggestions, or explanatory filler.
- Do not put long data blobs in the marked text. Long data should be placed in a file and referenced from the marked text instead.
- On success, the output must contain exactly one pair of 32173462130721312360912 markers.

## Context
### Project Context
#### Origin
```
{origin}
```

#### Goal
```
{goal}
```

### Hints
```
{hints}
```
