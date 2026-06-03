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
- A Markdown WriteUp is saved at `/mnt/project/reports/writeup.md`.
- A reusable solve/exploit script is saved under `/mnt/project/exploit/solve.*` whenever the path can be scripted.
- If a concrete script cannot be produced, the WriteUp explicitly explains why and gives exact manual commands, inputs, and verification steps.
- The Goal explicitly asks for an exploit or writeup and the required artifact is saved.

## Evidence rules

- Save flags to `/mnt/project/reports/flags.txt`.
- Save exploit scripts to `/mnt/project/exploit/`; prefer `/mnt/project/exploit/solve.py`, `solve.sh`, or another `solve.*` file for the final reusable path.
- Save the final Markdown WriteUp to `/mnt/project/reports/writeup.md`.
- Save scan output to `/mnt/project/recon/`.
- Save reverse / pwn / crypto intermediate files to `/mnt/project/vuln-research/`.
- If using a long-running listener, use `tmux` and record the session in `/mnt/project/cleanup/actions.md`.

## Required WriteUp content

`/mnt/project/reports/writeup.md` must include:

- Challenge summary and detected category.
- Attachment/service inventory used for the solve.
- Vulnerability or trick root cause.
- Step-by-step exploitation or solving commands.
- Final flag/proof and where it was obtained.
- Script path, or a clear reason no script is possible.

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
[cypher:finding type=FLAG confidence=1.0 severity=info tags=ctf,web artifacts=/mnt/project/reports/flags.txt,/mnt/project/reports/writeup.md,/mnt/project/exploit/solve.py cleanup=none] Recovered flag flag{example} from /var/www/html/config.php.
```

```text
[cypher:finding type=EXPLOIT_RESULT confidence=0.95 severity=high tags=ctf,pwn artifacts=/mnt/project/exploit/solve.py cleanup=none] The saved pwntools exploit reliably leaks libc and spawns a shell against the local challenge binary.
```
