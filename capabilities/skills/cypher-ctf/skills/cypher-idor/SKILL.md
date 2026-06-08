---
name: cypher-idor
description: Insecure Direct Object Reference and authorization bypass testing methodology covering sequential IDs, UUIDv1 prediction, hash-based ID traversal, batch parameter tampering, and multi-tenant isolation testing.
version: 0.1.0
owasp: [A01:2021-Broken Access Control]
cwe: [CWE-639]
finding_types: [PARAMETER, VULN_CANDIDATE, EXPLOIT_RESULT, SECRET_LEAK]
destructiveness: low
tags: [web, authorization, idor, access-control]
---

# Cypher IDOR / Authorization Bypass Skill

Use this skill when resources are identified by user-controllable references: numeric IDs, UUIDs, slugs, hashed IDs, or when the application lacks per-resource authorization checks.

## Detection methodology

1. Create two user accounts (User A and User B) with different privilege levels if possible.
2. As User A, create or access resources: profile, orders, messages, documents, API keys.
3. Record every identifier in URLs, request bodies, and API responses.
4. As User B, attempt to access User A's resources by substituting identifiers.
5. Check not just GET (read) but also PUT/PATCH (update) and DELETE (delete) — write/delete IDOR is higher severity.

## ID type recognition

| ID Type | Example | Attack |
|---------|---------|--------|
| Sequential integer | `/user/1234` | Increment/decrement |
| UUID v4 (random) | `/order/550e8400-e29b-...` | Find elsewhere (logs, emails, responses) |
| UUID v1 (timestamp) | `/doc/c5f7b180-xxxx-...` | Predictable — timestamp + MAC based |
| HashID/Hashids | `/file/LzNXR` | Decode common hashids salts or break the cipher |
| MongoDB ObjectId | `/post/507f1f77bcf86cd799439011` | Timestamp prefix predicts creation order |
| Slug | `/org/acme-corp` | Enumeration from other sources (Google dork, OSINT) |
| Encoded base64 | `/doc/eyJpZCI6MTIzNH0=` | Decode, tamper, re-encode |

## Testing checklist

### URL parameters and path segments
```
GET /api/users/1234 → GET /api/users/1235
GET /invoice?id=1001 → GET /invoice?id=1002
GET /api/v1/orders/100 → GET /api/v1/orders/101
```

### Request body parameters
```json
{"user_id": 1234, "action": "view"} → {"user_id": 1235, "action": "view"}
```

### Non-editable form fields (intercept and modify)
```html
<input type="hidden" name="user_id" value="1234">
```

### Cookie-based identifiers
```
Cookie: user_id=1234; session=... → Cookie: user_id=1235; session=...
```

### JWT/Token claims
Decode JWT, check if user identity is in a claim that can be changed: `{"sub": "1234"}` → `{"sub": "1235"}` (requires new signature unless alg=none attack also works — see cypher-jwt skill).

## Batch / mass assignment

When updating a resource, send extra fields that the API might bind:
```json
POST /api/users/update
{
  "name": "My Name",
  "email": "my@email.com",
  "role": "admin",
  "is_admin": true,
  "organization_id": 2
}
```
Test if `role`, `is_admin`, or ownership fields are mass-assignable.

## Multi-tenant isolation

- Change organization/tenant identifier: `GET /api/org/1/users` → `GET /api/org/2/users`
- Cross-tenant resource access: `GET /api/org/2/files/1234` (file 1234 belongs to org 1)
- Cross-tenant invitation/join: `POST /api/org/2/join` (should only be able to join own org)

## Testing order of operations

1. **Unauthenticated access**: Try the resource without any auth token/session.
2. **Cross-user access**: User B accessing User A's resources.
3. **Cross-role access**: Low-privilege user accessing admin resources.
4. **Cross-tenant access**: Org A user accessing Org B resources (if multi-tenant).
5. **Vertical privilege escalation**: User accessing higher-privilege endpoints without the required role.

## Evidence rules

- For each confirmed IDOR, save the two requests (authorized user and unauthorized user) to `/mnt/project/exploit/idor-<endpoint>/`.
- Redact PII/tokens from evidence but preserve the pattern.
- Rate severity based on: data sensitivity (PII/financial/credentials), write vs read, and number of affected records.
- For mass-assignment IDOR, save a diff showing added/modified fields not present in the original request.

## Automated detection

- **Autorize** (Burp extension): Automatically replays requests with alternate cookies.
- **AuthMatrix** (Burp extension): Tabular session management for multi-role testing.
- **ffuf**: `ffuf -w ids.txt -u "https://target/api/users/FUZZ" -H "Cookie: session=userB" -fs <expected-size>`

## Prefix examples

```text
[cypher:finding type=VULN_CANDIDATE confidence=0.9 severity=high tags=web,idor,read artifacts=/mnt/project/exploit/idor-user-profile/ cleanup=none] GET /api/users/1234/projects returns 200 for owner, and also 200 for user B with sequential ID 1235 — same response body including PII, suggesting no per-resource authorization check.
```

```text
[cypher:finding type=EXPLOIT_RESULT confidence=0.97 severity=critical tags=web,idor,write artifacts=/mnt/project/exploit/idor-user-profile/ cleanup=none] PATCH /api/users/1234 (as user B) successfully updates user A's email address. Write+Read IDOR on user profiles across the entire user base.
```

## Common false positives

- Resource returns 403/404 for User B but the app returns a generic "not found" instead of distinguishing between "doesn't exist" and "not yours." Verify by accessing a genuinely non-existent resource vs an out-of-scope resource as User A.
- Response bodies differ but the server correctly applies field-level RBAC — redacted fields with same HTTP status is NOT a vulnerability.
- The resource ID is a cryptographic random (UUIDv4) and never leaked — IDOR via brute force is not practical. Document as "no finding" unless the ID is discoverable via other channels.
