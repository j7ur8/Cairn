# Task
This is the **conclude phase** for Cypher Agent exploration.

You received a YAML graph and the current intent. You are NOT continuing the
task. Do not run commands. Do not wait for unfinished commands. Only summarize
facts already confirmed before this conclude prompt.

# Output contract

Return only one raw JSON object. Escape quotes.

Refuse:
```json
{"accepted": false, "reason": "policy_refusal"}
```

Normal:
```json
{"accepted": true, "data": {"description": "..."}}
```

# Required description format

`description` MUST start with:

```
[cypher:finding type=<TYPE> confidence=<0.0-1.0> severity=<info|low|medium|high|critical> tags=<csv> artifacts=<paths> cleanup=<none|required|done|tmux:NAME>] <confirmed factual conclusion>
```

If nothing meaningful was confirmed, return a `BLOCKER` fact with confidence
matching the strength of the negative evidence.

# Rules

- Stop immediately and output JSON now.
- Do not run more commands or inspect anything else.
- Include only objective facts already confirmed.
- Do not output plans, guesses, or filler.
- Do not repeat graph facts unless the current intent added a new confirmation.
- Store long data in files only if already stored; otherwise just reference the
  already-known path or say `artifacts=none`.

# Context
## Graph
```
{graph_yaml}
```

## Current Intent
```
{intent_id}
```

## Current Intent Description
```
{intent_description}
```
