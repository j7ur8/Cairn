Active prompt: bootstrap.md

# Task

Bootstrap collects initial target information from Origin, Goal, and Hints.

Use Origin as the starting point. Use Goal only to understand the requested success condition. 

Collect confirmed target profile facts. These may include target type, challenge type, services and entrypoints, technology stack and runtime characteristics, information from pages, public resources, attachments, source code, or other accessible materials, access boundaries, parameters, obvious abnormal behavior, and information disclosure clues.

Do not perform any actual vulnerability exploitation.

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
### Origin
```
{origin}
```

### Goal
```
{goal}
```

### Hints
```
{hints}
```
