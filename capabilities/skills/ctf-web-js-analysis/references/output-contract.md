# Output Contract

Both output files must be valid JSON and must not contain comments.

## Shared Fields

Top-level fields:

- `schema_version`: string, currently `"1.0"`.
- `target`: string or null.
- `generated_at`: ISO-8601 UTC timestamp.
- `tool`: string, usually `"ctf-web-js-analysis"`.
- `notes`: array of strings.

Every finding must include:

- `id`: stable local id such as `api-001` or `leak-001`.
- `source`: object describing where the finding came from.
- `evidence`: array of evidence objects.
- `confidence`: one of `runtime_confirmed`, `static_high`, `static_candidate`, `inferred_low`.

## information_api.json

Top-level field:

- `apis`: array of API finding objects.

API finding fields:

- `id`: string.
- `url`: absolute URL or path.
- `method`: HTTP method string or null.
- `parameters`: array of objects with `name`, `location`, `required`, `evidence`.
- `headers`: array of observed header names or objects; omit secret values.
- `auth_context`: string or null.
- `source`: source object.
- `evidence`: evidence object array.
- `confidence`: confirmation level.
- `notes`: array of strings.

Parameter `location` values:

- `query`
- `body`
- `path`
- `header`
- `cookie`
- `unknown`

Do not invent `required=true`. Use `null` unless the requirement is directly observed.

## information_leak.json

Top-level field:

- `leaks`: array of leak finding objects.

Leak finding fields:

- `id`: string.
- `type`: leak category such as `api_key`, `jwt`, `credential`, `private_key`, `internal_host`, `source_map`, `debug_config`, `dependency_vulnerability`, or `other`.
- `summary`: short human-readable description.
- `value_redacted`: redacted value or null.
- `value_sha256`: SHA-256 of the raw value when available and safe to compute.
- `severity`: `info`, `low`, `medium`, `high`, or `unknown`.
- `source`: source object.
- `evidence`: evidence object array.
- `confidence`: confirmation level.
- `notes`: array of strings.

Never place a full reusable credential in `value_redacted`.

## Source Object

Recommended fields:

- `type`: `business_js`, `third_party`, `defensive_js`, `source_map`, `config`, `har`, `html`, or `unknown`.
- `url`: source URL or null.
- `local_path`: local artifact path or null.
- `sha256`: file hash or null.
- `line`: line number or null.
- `column`: column number or null.
- `tool`: tool that produced the finding or null.

## Evidence Object

Recommended fields:

- `kind`: `static_match`, `runtime_request`, `har_entry`, `source_map`, `tool_output`, `manual_review`, or `derived`.
- `description`: short explanation.
- `snippet`: short matched snippet with secrets redacted.
- `artifact`: path to saved evidence file or null.
- `request_id`: browser/HAR request id or null.
- `timestamp`: ISO-8601 UTC timestamp or null.

Evidence must be sufficient for another analyst to find the same source again.
