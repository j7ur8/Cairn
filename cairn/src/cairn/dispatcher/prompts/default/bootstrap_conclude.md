# Task
You can not and do not execute any command except read. You do not need to wait for unfinished tasks or commands. You will receive a context bundle containing Origin, Goal, and Hints.

Do not continuing exploration here and must not generate an action plan. You only need to summarize the bootstrap initial reconnaissance facts that have already been confirmed during target business identification and initial information collection.

## Output Requirements
For a normal successful result, return only the confirmed facts as plain text surrounded by 32173462130721312360912. Do not output JSON. Do not output anything outside the markers.

If you cannot produce a successful fact summary, output a plain error explanation without 32173462130721312360912.

Normal return example:
```text
32173462130721312360912Confirmed fact summary...32173462130721312360912
```

### Rules
- The marked text must contain already confirmed objective factual conclusions. Do not output plans, guesses, or explanatory filler.
- Do not continue exploration, do not infer missing details, and do not propose next steps.
- Do not put long data blobs in the marked text.
- On success, the output must contain exactly one pair of 32173462130721312360912 markers.

## Context
Origin and Goal are available in the task-local project context file referenced by CLAUDE.md/AGENTS.md.

### Hints
```
{hints}
```
