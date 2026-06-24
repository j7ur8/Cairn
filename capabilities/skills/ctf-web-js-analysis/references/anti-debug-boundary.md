# Anti-Debug Boundary

This skill identifies defensive frontend components and records their impact. It does not bypass them by default.

## Signals

Classify JavaScript as defensive when it contains strong evidence of:

- Repeated `debugger` traps, timing checks, console tamper checks, or devtools detection.
- Dynamic cookie, header, nonce, or token generation required before ordinary requests.
- Obfuscated challenge scripts loaded from WAF, anti-bot, or risk-control endpoints.
- Redirect loops, challenge pages, or request blocking tied to browser fingerprint state.
- RuiShu-like behavior: dynamic cookie issuance, obfuscated VM-style script, browser feature probing, and immediate request replay dependency.

## Record

For each boundary, capture:

- Script URL and local hash.
- Trigger condition.
- Generated cookie/header/token names, with values redacted unless non-secret.
- Request dependency: which API fails without the dynamic value.
- Browser evidence: HAR request id, status, redirect, console error, or screenshot path.
- Whether normal browsing still collected enough static artifacts.

## Degrade

If defensive code prevents collection:

- Keep all static files already collected.
- Save HTML/HAR evidence of the block.
- Mark impacted API findings as `inferred_low` or `static_candidate`.
- Recommend a runtime reverse workflow only when token/signature reproduction is in scope.

## Do Not Do By Default

- Patch challenge scripts.
- Disable browser APIs to evade detection.
- Replay or forge WAF tokens.
- Scale requests to map the protection.
- Claim bypass feasibility from static signatures alone.
