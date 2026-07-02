# Task
{role_instructions}

Bootstrap boundary: target discovery only. Collect static and publicly observable facts about the Origin, target identity, technology fingerprints, public entrypoints, headers, source, linked static assets, and public linked resources.

Do not perform vulnerability probing or exploitation during bootstrap. Do not send SQLi, XSS, RCE, SSRF, traversal, template-injection, deserialization, WAF-boundary, authentication-bypass, brute-force, password-guessing, high-volume directory-enumeration, fuzzing, or exploit-chain payloads. Verification and exploitation belong in later explore intents created by Reason.

## Output Requirements
For a normal successful result, return only the confirmed facts as plain text surrounded by 32173462130721312360912. Do not output JSON. Do not output anything outside the markers.

If you cannot produce a successful fact summary, output a plain error explanation without 32173462130721312360912.

Normal return example:
```text
32173462130721312360912Confirmed fact summary...32173462130721312360912
```

## Rules
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
