# Output Contract

Both output files must be valid JSON and must not contain comments.

## Top-Level Fields Shared By Both Files

Both `information_api.json` and `information_leak.json` must include these top-level fields:

- `schema_version`: string, currently `"1.0"`.
- `target`: string or null; the target URL, host, or challenge identifier when known.
- `generated_at`: ISO-8601 UTC timestamp.
- `tool`: string, usually `"ctf-web-js-analysis"`.
- `notes`: array of strings for file-level context, collection gaps, or assumptions. Use `[]` when there is nothing to add.

## Finding Fields Shared By API And Leak Findings

Every API and leak finding must include:

- `id`: stable local id such as `api-001` or `leak-001`.
- `source`: object describing where the finding came from. Use the Source Object format below.
- `evidence`: array of evidence objects. Use the Evidence Object format below.
- `value`: the value of this API or leak for obtaining the flag.

`value` is not evidence confidence. It describes how useful the finding is for building a flag-winning exploit path:

- `high`: directly points to the flag, an authentication bypass, an injection point, important source/query logic, a reusable key, or another immediately exploitable primitive.
- `medium`: helps build an exploit chain, such as API parameters, backend technology, path structure, source maps, or sensitive configuration clues.
- `low`: weakly related signal, such as ordinary version information, ordinary routes, or non-sensitive metadata.
- `info`: background record with little or no direct help toward obtaining the flag.

## information_api.json

Top-level field:

- `apis`: array of API finding objects.

API finding fields:

- `id`: string.
- `url`: absolute URL or path.
- `method`: HTTP method string or null.
- `parameters`: array of objects with `name`, `location`, `required`, `evidence`.
- `headers`: array of observed header names or objects; omit secret values.
- `auth_context`: observed authentication context for this API, or `null` when no requirement was observed.
- `source`: source object.
- `evidence`: evidence object array.
- `value`: `high`, `medium`, `low`, or `info`.
- `notes`: array of strings for API-specific caveats, uncertainty, or follow-up ideas. Use `[]` when there is nothing to add.

`auth_context` is descriptive, not a strict enum. Prefer concise strings such as `anonymous`, `authenticated_session`, `cookie_required`, `bearer_token_required`, `csrf_token_required`, or `unknown_auth_flow` when observed from code or runtime evidence. Do not infer authentication requirements from endpoint names alone.

Parameter `location` describes where the parameter appears in the HTTP request:

- `query`: query string, such as `?id=123`.
- `body`: request body, such as JSON, form data, or multipart data.
- `path`: path segment, such as `/api/users/{id}`.
- `header`: HTTP header.
- `cookie`: cookie value.
- `unknown`: parameter name was observed, but its request location was not.

Do not invent `required=true`. Use `null` unless the requirement is directly observed.

## information_leak.json

Top-level field:

- `leaks`: array of leak finding objects.

Leak finding fields:

- `id`: string.
- `value`: `high`, `medium`, `low`, or `info`.
- `type`: leak category such as `api_key`, `jwt`, `credential`, `private_key`, `internal_host`, `source_map`, `debug_config`, `dependency_vulnerability`, or `other`.
- `source`: source object.
- `evidence`: evidence object array.

Never place a full reusable credential in `evidence.snippet` or any other output field.

Example empty templates:

```json
{
  "schema_version": "1.0",
  "target": null,
  "generated_at": "2026-06-24T00:00:00Z",
  "tool": "ctf-web-js-analysis",
  "notes": [],
  "apis": []
}
```

```json
{
  "schema_version": "1.0",
  "target": null,
  "generated_at": "2026-06-24T00:00:00Z",
  "tool": "ctf-web-js-analysis",
  "notes": [],
  "leaks": []
}
```

Example API finding:

```json
{
  "id": "api-001",
  "url": "/api/search",
  "method": "GET",
  "parameters": [
    {
      "name": "q",
      "location": "query",
      "required": null,
      "evidence": [
        {
          "kind": "static_match",
          "description": "Fetch wrapper appends q to URLSearchParams.",
          "snippet": "params.set(\"q\", searchTerm)",
          "artifact": "artifacts/js/app.pretty.js",
          "request_id": null,
          "timestamp": null
        }
      ]
    }
  ],
  "headers": [],
  "auth_context": "anonymous",
  "source": {
    "type": "business_js",
    "url": "https://example.test/app.js",
    "local_path": "artifacts/js/app.js",
    "sha256": null,
    "line": 42,
    "column": null,
    "tool": "manual_review"
  },
  "evidence": [
    {
      "kind": "static_match",
      "description": "Endpoint literal found in business JS.",
      "snippet": "fetch(`/api/search?${params}`)",
      "artifact": "artifacts/js/app.pretty.js",
      "request_id": null,
      "timestamp": null
    }
  ],
  "value": "medium",
  "notes": []
}
```

Example leak finding:

```json
{
  "id": "leak-001",
  "value": "high",
  "type": "api_key",
  "source": {
    "type": "config",
    "url": "https://example.test/config.js",
    "local_path": "artifacts/js/config.js",
    "sha256": null,
    "line": 8,
    "column": null,
    "tool": "gitleaks"
  },
  "evidence": [
    {
      "kind": "tool_output",
      "description": "Scanner reported a redacted API key-like value in public config.",
      "snippet": "PUBLIC_API_KEY=pk_live_...REDACTED",
      "artifact": "artifacts/scans/gitleaks.json",
      "request_id": null,
      "timestamp": null
    }
  ]
}
```

## Source Object

Recommended fields:

- `type`: `business_js`, `third_party`, `defensive_js`, `source_map`, `config`, `har`, `html`, or `unknown`.
- `url`: source URL or null.
- `local_path`: local artifact path or null.
- `sha256`: file hash or null.
- `line`: line number or null.
- `column`: column number or null.
- `tool`: tool that produced the finding or null.

Use `source` to identify the closest reproducible origin of the finding: the JS file that contains an endpoint, the HAR entry that observed a request, the source map that exposed original code, the config file that contained a leak, or the scanner/manual review that produced the finding. If a field is unknown, keep the key and use `null` where practical; do not guess.

## Evidence Object

Recommended fields:

- `kind`: `static_match`, `runtime_request`, `har_entry`, `source_map`, `tool_output`, `manual_review`, or `derived`.
- `description`: short explanation.
- `snippet`: short matched snippet with secrets redacted.
- `artifact`: path to saved evidence file or null.
- `request_id`: browser/HAR request id or null.
- `timestamp`: ISO-8601 UTC timestamp or null.

Use `evidence` to explain why the finding exists and how another analyst can reproduce it. Good evidence includes a short redacted snippet, a saved artifact path, a HAR request id, a tool output reference, or a manual review note tied to a source location. Evidence must be sufficient for another analyst to find the same source again.

Never put a complete reusable credential in `evidence.snippet`, `notes`, or any other field.
