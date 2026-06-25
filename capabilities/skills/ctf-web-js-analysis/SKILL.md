---
name: ctf-web-js-analysis
description: Static-first CTF Web JavaScript analysis for collecting visible JS, extracting API endpoints and leak evidence, enumerating source maps/chunks/manifests, and producing information_api.json plus information_leak.json before deeper JS reverse engineering.
---

# CTF Web JS Static Analysis

Use this skill for authorized CTF, cyber range, or explicitly permitted Web targets when the task is to inventory frontend JavaScript, recover public API surfaces, inspect source maps/chunks, identify exposed configuration or secrets, and prepare evidence for later runtime reverse engineering.

## Authorization Boundary

- Work only in CTF, lab, owned, or explicitly authorized environments.
- During bootstrap, do not brute force, bypass WAF controls, evade anti-bot protections, or run large fuzzing campaigns.
- Treat anti-debug, RuiShu-like, WAF, bot-defense, and telemetry scripts as boundaries to identify and record, not systems to bypass by default.
- Never invent endpoints, parameters, tokens, or leak impact. Record only what is directly observed or inferred from stated evidence.

## Required Outputs

Always produce both files in `reports/ctf-web-js-analysis/`:

- `reports/ctf-web-js-analysis/information_api.json`
- `reports/ctf-web-js-analysis/information_leak.json`

Every finding must include `source`, `evidence`, and `value`. Use `value` to rate how useful the API or leak is for obtaining the flag, not to express evidence confidence. If no findings are present, write valid empty files using `scripts/init_outputs.py`.

Read [references/output-contract.md](references/output-contract.md) before finalizing these files.

## Workflow

1. Initialize output files:
   `python3 <skill>/scripts/init_outputs.py --directory reports/ctf-web-js-analysis`
2. Collect entry evidence:
   - HTML entry pages and inline scripts.
   - Browser HAR and network request exports when `chrome-devtools-host` is available.
   - Manifest files, service workers, preload hints, import maps, and sourcemap pointers.
3. Recursively expand visible JS:
   - Extract script URLs from HTML, HAR, manifest, service worker, source map, and JS bundle text.
   - Follow chunks and source map references in scope.
   - Keep business JS, third-party libraries, defensive scripts, source maps, and config files separate in notes and inventory.
4. Normalize inventory:
   `python3 <skill>/scripts/normalize_js_inventory.py --root <download-dir> --urls <js_urls.json> --output reports/ctf-web-js-analysis/js_inventory.json`
5. Format and scan:
   - Use `js-beautify` or equivalent formatting before manual review.
   - Use LinkFinder/xnLinkFinder/jsluice style endpoint extraction where available.
   - Use gitleaks/trufflehog style leak scanning where available.
   - Use retire.js only to identify vulnerable third-party library versions; do not mix this with business API findings.
6. Merge evidence:
   `python3 <skill>/scripts/merge_api_leak_findings.py --artifact-dir reports/ctf-web-js-analysis --output-dir reports/ctf-web-js-analysis [--tool-output ...]`
7. Validate final JSON outputs:
   `python3 <skill>/scripts/validate_outputs.py --directory reports/ctf-web-js-analysis`
8. Cross-check dynamically only when authorized and useful:
   - Use browser runtime requests/HAR to confirm candidate endpoints and parameter names.
   - Do not send guessed exploit payloads during this skill's bootstrap pass.

For the full phase checklist and pass/fail criteria, read [references/workflow.md](references/workflow.md). For tool command examples, read [references/tooling.md](references/tooling.md). For defensive JavaScript boundaries, read [references/anti-debug-boundary.md](references/anti-debug-boundary.md).

## Classification Rules

- `business_js`: application bundles, route modules, API clients, feature code.
- `third_party`: framework/runtime/vendor libraries, CDN scripts, analytics SDKs.
- `defensive_js`: anti-debug, bot-defense, RuiShu-like, WAF challenge, integrity or telemetry code.
- `source_map`: `.map` files and `sourcesContent` recovered from them.
- `config`: public JSON, env bootstrap blobs, manifest data, service-worker caches, build metadata.

Record the classification in inventory and finding `source.type` where possible.

## Anti-Debug And WAF Components

When defensive JavaScript is present:

- Identify file URL, hash, trigger condition, dynamic cookie/token/header names, and observed request dependency.
- Record browser evidence such as redirect loops, challenge endpoints, or generated cookies.
- Defer bypass, patching, or signing-token reproduction to a later authorized runtime reverse workflow such as `js-reverse-automation`.

## Evidence Standards

- API findings need method, URL/path, parameters, and evidence whenever observed. If method or parameters are unknown, use `null` or an empty list and rate `value` according to utility for obtaining the flag.
- Leak findings need leak type, value rating, source location, and evidence. Keep redacted samples or fingerprints inside evidence only when they are safe and useful for reproduction.
- Source locations should include file path or URL, line/column when available, and SHA-256 when a local file exists.
- Evidence should be short and reproducible: command output path, HAR request id, matched snippet, or runtime request metadata.
- Final reports should explain API and leak findings by their `value`: why each high or medium item helps reach the flag, and why low or info items are only supporting context.

## Bundled Tools

Third-party source snapshots live under `tools/vendor/` and are tracked in `tools/vendor_manifest.json`. These directories are not submodules; nested `.git` directories are removed after fetch. Use `scripts/install_vendor_tools.sh` to install/build dependencies inside each vendor directory when needed.
