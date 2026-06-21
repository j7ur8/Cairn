# Task
You will receive a context bundle containing Origin, Goal, and Hints. Your job in this bootstrap phase is bounded initial reconnaissance: identify the target business purpose, application type, technical fingerprints, entrypoints, parameters, authentication boundary, public resources, and any directly observable abnormal behavior.

{role_instructions}

## Output Requirements
For a normal successful result, return only the confirmed facts as plain text surrounded by 32173462130721312360912. Do not output JSON. Do not output anything outside the markers.

If you cannot produce a successful fact summary, output a plain error explanation without 32173462130721312360912.

Normal return example:
```text
32173462130721312360912Confirmed fact summary...32173462130721312360912
```

## Rules
- This phase is for one bounded pass of target business identification and initial information collection. Do not continue until Goal is achieved unless Goal is directly confirmed during this bounded pass.
- Allowed light probing includes visiting Origin, following normal redirects, reading page source and response headers, inspecting publicly linked JavaScript and CSS, and trying a few obvious public paths or basic form behaviors.
- Do not perform deep exploitation, brute force, password guessing, large fuzzing, long blind injection or enumeration, destructive requests, or other high-volume or intrusive activity.
- The marked text must clearly state only confirmed reconnaissance facts that help Reason build the next intents. If a CTF flag or proof is directly exposed in public content, include it as a confirmed fact.
- The marked text must contain only already confirmed objective factual conclusions. Do not output plans, guesses, next-step suggestions, or explanatory filler.
- Do not put long data blobs in the marked text. Long data should be placed in a file and referenced from the marked text instead.
- On success, the output must contain exactly one pair of 32173462130721312360912 markers.

{capability_instructions}

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
