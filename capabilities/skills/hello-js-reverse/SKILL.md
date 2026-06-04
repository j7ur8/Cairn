---
name: hello-js-reverse
description: Frontend JavaScript reverse-engineering workflows that pair the camoufox-reverse-mcp browser MCP with the hello_js_reverse_skill reference material shipped alongside this skill.
version: 0.1.0
---

# Hello JS Reverse Skill

Use this skill when the project goal involves unpacking, debugging, or
modifying JavaScript that runs in a real browser. Typical targets include
login pages with anti-bot JS, fingerprint/canvas scripts, slider/turnstile
verifications, encrypted payload decoders, and webpack/babel bundles that
must be re-executed in a controlled environment.

## When to load

- The goal mentions logging into a web app whose JS you do not control.
- The goal mentions reversing, replaying, hooking, or bypassing client-side
  JavaScript checks.
- A previous reason / explore turn has produced a URL that requires JS to
  render a meaningful response.

## Profile and state

- Browser profile directory: `/mnt/project/.browser-profile/`
  - Persistent across runs in the same project; survives `sleep infinity`
    recycle.
  - Reuse the same profile across sibling intents so cookies, IndexedDB,
    service workers, and localStorage are preserved between calls.
- The camoufox-reverse-mcp is started with `CAMOUFOX_PROFILE_DIR` pointing at
  this path and `CAMOUFOX_HEADLESS=1` by default (see `dispatch.yaml`).

## Reference material

The reference workflow `hello_js_reverse_skill` is bundled inside the worker
image at the path documented by the mcp server. Read it before issuing
explore turns that touch the live site: the reference captures the
boilerplate sequence (launch profile, navigate, capture network/storage
artifacts, dump rendered DOM) that the agent should mirror.

## Proxy

- The browser inherits the project-level proxy selected at project creation
  (see Server Settings > Proxies). When a proxy is set, the worker
  container's `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` env vars are
  populated automatically and the MCP launch picks them up.
- When no proxy is selected, the browser connects directly. Use
  `chrome://settings` or the MCP `proxy_set` tool (if available) to point
  the browser at a custom endpoint without changing the project assignment.

## Completion standards

A JS reverse task is complete only when one of these is confirmed:

- The intended JS state is reproduced in a script under
  `/mnt/project/exploit/solve.*` and the script can be re-run with the same
  inputs to produce the same output.
- A replayer / hook set is saved at `/mnt/project/exploit/` that can drive
  the target endpoint without a real browser.
- A Markdown report at `/mnt/project/reports/writeup.md` documents the
  observed call graph, the relevant transformed snippets, and the manual
  reproduction steps (including any browser DevTools network captures saved
  under `/mnt/project/recon/`).

## Evidence rules

- Save network captures to `/mnt/project/recon/`.
- Save decoded payloads, deobfuscated JS, and hooked variants to
  `/mnt/project/vuln-research/`.
- Save reusable reproduction scripts to `/mnt/project/exploit/`.
- Save the final writeup to `/mnt/project/reports/writeup.md`.
- Never commit `/mnt/project/.browser-profile/` — it contains real session
  cookies. Add it to the project's `.gitignore` if the host directory is
  under git.
