---
name: cypher-flag-oob
description: Flag submission, OOB callback, reverse listener and long-running tmux session conventions for Cypher Agent.
version: 0.1.0
---

# Cypher Flag / OOB Skill

Use this skill when a task needs CTF flag submission, DNSLog/OOB verification, callback infrastructure, reverse shell listeners, or other long-running support processes.

## Flag handling

- Preserve exact flag bytes and casing.
- Save flags to `/mnt/project/reports/flags.txt`.
- Submit only when challenge instructions or environment variables define a submission endpoint.
- Record submission request/response in `/mnt/project/reports/flag-submit.*`.
- Do not brute force the submit endpoint.

If TSEC-style variables are present:

```bash
curl -X POST "http://${TSEC_SERVER_HOST}/api/submit" \
  -H "Agent-Token: ${TSEC_AGENT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"code":"<challenge_code>","flag":"<flag>"}'
```

Use only with high confidence and save the server response.

## OOB / callbacks

- Use `CAIRN_DNSLOG_URL` when configured for DNSLog/OOB checks.
- Use configured remote SSH support only as authorized support infrastructure.
- Record every callback payload and result in `/mnt/project/exploit/oob.md`.
- For blind SSRF/XXE/RCE, a successful callback is an `OOB_CALLBACK` fact.

## Long-running listeners

Always use `tmux`:

```bash
tmux new-session -d -s cypher-listener 'python3 -m http.server 8000'
tmux ls
```

Record cleanup:

```bash
mkdir -p /mnt/project/cleanup
printf 'tmux kill-session -t cypher-listener\n' >> /mnt/project/cleanup/actions.md
```

Prefix example:

```text
[cypher:finding type=OOB_CALLBACK confidence=0.93 severity=high tags=ssrf,oob artifacts=/mnt/project/exploit/oob.md cleanup=tmux:cypher-listener] The target fetched the unique callback URL, confirming blind SSRF from the avatar import endpoint.
```
