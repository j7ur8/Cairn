# Task
You can not and do not execute any command except read. You do not need to wait for unfinished tasks or commands. You will receive a context bundle containing Origin, Goal, and Hints. 
You need to understand your starting point and the information already available (Origin and Hints), then become an expert in this domain.
But note that you are not continuing the task here. You only need to summarize the key facts that have already been confirmed so far and are most helpful for reaching Goal.

## Output Requirements
For a normal successful result, return only the confirmed facts as plain text surrounded by 32173462130721312360912. Do not output JSON. Do not output anything outside the markers.

If you cannot produce a successful fact summary, output a plain error explanation without 32173462130721312360912.

Normal return example:
```text
32173462130721312360912Confirmed fact summary...32173462130721312360912
```

### Rules
- The marked text must contain already confirmed objective factual conclusions. Do not output plans, guesses, or explanatory filler.
- Do not put long data blobs in the marked text.
- On success, the output must contain exactly one pair of 32173462130721312360912 markers.

# Context
## Origin
```
{origin}
```

## Goal
```
{goal}
```

## Hints
```
{hints}
```
