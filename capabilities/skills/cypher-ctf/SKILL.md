---
name: cypher-ctf
description: CTF orchestration skill — triages challenge type, delegates to specialist sub-skills (pwn, reverse, crypto, forensics, web), coordinates multi-step solve paths, and enforces evidence/writeup standards.
version: 0.2.0
---

# Cypher CTF Skill (Orchestration Layer)

Use this skill when the project looks like a CTF challenge, cyber range, HTB/THM-style box, or competition sandbox. This skill acts as the **orchestration layer** — it triages, delegates to specialist sub-skills, and coordinates the overall solve path.

## Sub-skill delegation

When a challenge category is identified, load the corresponding specialist skill for detailed methodology:

| Category | Sub-skill | Key role |
|----------|-----------|----------|
| Web | `cypher-sqli`, `cypher-xss`, `cypher-ssrf`, `cypher-command-injection`, `cypher-file-upload`, `cypher-idor`, `cypher-deserialization`, `cypher-xxe`, `cypher-jwt`, `cypher-auth-bypass`, `cypher-ssti` | Web exploit chains |
| Pwn / Binary | `cypher-pwn` | Stack/heap/ROP |
| Reverse | `cypher-reverse` | Disassembly, deobfuscation |
| Crypto | `cypher-crypto` | Cipher attacks, oracle exploitation |
| Forensics / Stego | `cypher-forensics` | File carving, memory analysis |
| Blockchain | `cypher-blockchain` | Smart contract exploits |
| Full-box | All of the above + post-exploit sub-skills | Multi-stage compromise |

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
3. Load the appropriate specialist sub-skill(s) from `capabilities/skills/`.
4. Build one narrow path to the goal before broadening.
5. Prefer exact reproducibility over broad speculation.
6. If a path fails, write a `BLOCKER` fact with the decisive negative evidence.

## Common lanes

- `recon`: asset and attachment inventory.
- `web_exploit`: endpoint, auth, upload, SSRF, SQLi, command injection, deserialization, SSTI.
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
