# Task

Do not perform vulnerability probing or exploitation during bootstrap. Do not send SQLi, XSS, RCE, SSRF, traversal, template-injection, deserialization, WAF-boundary, authentication-bypass, brute-force, password-guessing, high-volume directory-enumeration, fuzzing, or exploit-chain payloads. Verification and exploitation belong in later explore intents created by Reason.

Bootstrap boundary: target discovery and profiling only. Build a concise target profile from static, provided, and publicly observable facts about the Origin, target identity, purpose, exposed entrypoints or artifacts, technology and runtime fingerprints, access boundaries, supplied materials, linked public resources, constraints, and directly observable abnormal behavior.

Allowed bootstrap activity is limited to non-intrusive target profiling: inspect the Origin and any normally reachable or explicitly provided materials, follow ordinary redirects or references, record observable responses and artifacts, and perform only minimal interactions needed to confirm the target identity, shape, and access boundary.

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
Origin and Goal are available in the task-local project context file referenced by CLAUDE.md/AGENTS.md.

### Hints
```
{hints}
```
