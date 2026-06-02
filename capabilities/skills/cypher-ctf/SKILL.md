---
name: cypher-ctf
description: CTF automation workflows for web, pwn, reverse, crypto, forensics, stego and misc tasks.
version: 0.1.0
---

# Cypher CTF Skill

Use this skill when the project looks like a CTF challenge, cyber range, HTB/THM-style box, or competition sandbox.

## Completion standards

A CTF task is complete only when one of these is confirmed:

- The requested `flag{...}` / platform-specific flag is recovered.
- The platform submit API returns success.
- The requested shell / user / root proof is confirmed.
- The Goal explicitly asks for an exploit or writeup and the required artifact is saved.

## Evidence rules

- Save flags to `/mnt/project/reports/flags.txt`.
- Save exploit scripts to `/mnt/project/exploit/`.
- Save scan output to `/mnt/project/recon/`.
- Save reverse / pwn / crypto intermediate files to `/mnt/project/vuln-research/`.
- If using a long-running listener, use `tmux` and record the session in `/mnt/project/cleanup/actions.md`.

## Fast triage

1. Read Origin, Goal, Hints, and `/mnt/attachments`.
2. Identify category: web / pwn / reverse / crypto / forensics / stego / misc / full-box.
3. Build one narrow path to the goal before broadening.
4. Prefer exact reproducibility over broad speculation.
5. If a path fails, write a `BLOCKER` fact with the decisive negative evidence.

## Common lanes

- `recon`: asset and attachment inventory.
- `web_exploit`: endpoint, auth, upload, SSRF, SQLi, command injection, deserialization.
- `service_exploit`: version-specific service exploitation, default creds, protocol bugs.
- `ctf_specialist`: pwn/reverse/crypto/forensics/stego transforms.
- `post_exploit`: shell stabilization, local enum, privesc, flag collection.

## Output prefix examples

```text
[cypher:finding type=FLAG confidence=1.0 severity=info tags=ctf,web artifacts=/mnt/project/reports/flags.txt cleanup=none] Recovered flag flag{example} from /var/www/html/config.php.
```

```text
[cypher:finding type=EXPLOIT_RESULT confidence=0.95 severity=high tags=ctf,pwn artifacts=/mnt/project/exploit/solve.py cleanup=none] The saved pwntools exploit reliably leaks libc and spawns a shell against the local challenge binary.
```
