# Task
This is the **conclude phase** for Cypher Agent bootstrap.

You received Origin, Goal, and Hints. You are NOT continuing the task. Do not
run commands. Do not wait for unfinished commands. Only summarize facts already
confirmed before this conclude prompt.

# Output contract

Return only one raw JSON object. Escape quotes.

Refuse:
```json
{"accepted": false, "reason": "policy_refusal"}
```

Normal:
```json
{"accepted": true, "data": {"fact": {"description": "..."}}}
```

# Required fact format

`fact.description` MUST start with:

```
[cypher:finding type=<TYPE> confidence=<0.0-1.0> severity=<info|low|medium|high|critical> tags=<csv> artifacts=<paths> cleanup=<none|required|done|tmux:NAME>] <confirmed factual conclusion>
```

If nothing meaningful was confirmed, return a `BLOCKER` fact with
`artifacts=none`.

# Rules

- Stop immediately and output JSON now.
- Do not run more commands or inspect anything else.
- Do not output `complete` in this phase.
- Include only objective facts already confirmed.
- Do not output plans, guesses, or filler.
- Long data must be referenced by path if it was already saved.

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
