# Workflow Reference

## Phase 0: Scope And Artifact Setup

- Confirm the target is CTF, lab, owned, or explicitly authorized.
- Create an artifact directory for all inputs and outputs.
- Run `scripts/init_outputs.py` so empty result files exist before scanning starts.
- Record target URL, collection time, browser profile state, and any authentication context that was intentionally used.

Success: artifact directory contains valid `information_api.json` and `information_leak.json`.

Failure: target is not authorized, or the requested activity requires bypass/fuzzing outside this skill's bootstrap boundary.

## Phase 1: Entry Collection

Collect:

- Entry HTML and redirect chain.
- All script tags, preload/modulepreload links, import maps, inline scripts.
- HAR/network export from browser runtime when available.
- Web app manifest, service worker script, workbox precache manifest, route manifests.
- JavaScript source maps and chunk references.

Success: every visible entry point has a saved local copy or a recorded reason why it was unavailable.

Failure: collection only contains a screenshot or page title without inspectable HTML/network evidence.

## Phase 2: Recursive JS Expansion

Use `scripts/collect_js_urls.py` on HTML, HAR, manifest, service-worker, source-map, and JS files. Resolve relative URLs against the entry URL when known.

Follow:

- `src`, `href`, dynamic `import()`, `importScripts()`, `new Worker()`, `sourceMappingURL`.
- Webpack/Vite/Next/Nuxt chunk manifests.
- Source map `sources` and `sourcesContent` only as static evidence.

Stop when no new in-scope JS, map, manifest, or config URLs are found.

Success: inventory explains how each JS URL was discovered.

Failure: bundle chunks are noted but not collected, or source maps are used without preserving original map evidence.

## Phase 3: Inventory And Formatting

Run `scripts/normalize_js_inventory.py` to produce `js_inventory.json`.

Classify each item:

- `business_js`
- `third_party`
- `defensive_js`
- `source_map`
- `config`
- `unknown`

Beautify minified scripts before manual review. Keep original files unchanged and write formatted copies to a derived directory if needed.

Success: each local JS file has URL, local path, SHA-256, discovery source, confidence, and source-map indicator.

Failure: hashes or source URLs are missing for files used as evidence.

## Phase 4: API Extraction

Extract candidate endpoints from:

- Literal URLs and paths.
- Fetch/XHR/axios/jQuery wrappers.
- OpenAPI/GraphQL clients or generated SDKs.
- Route definitions and service-worker cache lists.
- HAR/runtime requests.

For each candidate, record:

- Method if observed or statically declared.
- Path/URL.
- Parameter names and their evidence.
- Auth or dynamic headers only when observed.
- Value for obtaining the flag: `high`, `medium`, `low`, or `info`.

Success: `information_api.json` contains no fabricated parameters and every entry cites evidence.

Failure: endpoints are listed without source/evidence, or guessed parameters are presented as confirmed.

## Phase 5: Leak Extraction

Scan for:

- API keys, tokens, credentials, private keys, JWTs, webhook URLs.
- Internal hostnames, debug flags, source map disclosures, cloud bucket URLs.
- Build metadata, sourcemap `sourcesContent`, comments with sensitive references.
- Vulnerable third-party library versions as dependency findings.

Redact secrets by default. Keep enough safe evidence shape for reproducibility, such as prefix/suffix and hash, only in evidence fields.

Success: `information_leak.json` uses only `id`, `value`, `type`, `source`, and `evidence`; each `value` explains utility for obtaining the flag.

Failure: full secret values are unnecessarily printed into final prose or unsupported impact is claimed.

## Phase 6: Dynamic Cross-Validation

Use browser runtime only to confirm observations:

- Match static endpoint candidates with HAR requests.
- Confirm methods, parameters, cookies, tokens, and headers that naturally occur while browsing.
- Capture request ids, timestamps, and response status.

Do not brute force, bypass defenses, or fuzz parameter values as part of this skill.

Success: high-value findings have both static and runtime evidence when available.

Failure: runtime activity changes from observation into exploitation without explicit authorization.

## Phase 7: Final Handoff

Provide:

- Paths to `information_api.json`, `information_leak.json`, and `js_inventory.json`.
- Any missing collection gaps.
- Defensive JS boundary notes.
- A value-based explanation of how high and medium API/leak findings help reach the flag.
- Recommended next skill only if needed, such as `js-reverse-automation` for token/signature reproduction.

Before final handoff, run:

`python3 <skill>/scripts/validate_outputs.py --directory <artifact-dir>`
