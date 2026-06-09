---
name: cypher-vuln-research
description: Vulnerability research orchestration skill — coordinates source audit, CVE reproduction, PoC adaptation, fuzzing, root-cause analysis, evidence collection, and research report generation.
version: 0.2.0
---

# Cypher Vulnerability Research Skill (Orchestration Layer)

Use this skill for source-code audit, CVE reproduction, exploit adaptation, binary analysis, fuzzing, or patch-diff research. This skill acts as the **orchestration layer** — it triages the target, chooses focused research lanes, and coordinates root-cause evidence.

## Research lanes

The CTF specialist skills are bundled under `cypher-ctf/skills/`, and pentest AD/cloud/container specialist skills are bundled under `cypher-pentest/skills/`. They are not independently injected with this skill. Use the lanes below as methodology categories unless a project explicitly selects those orchestration skills too.

| Research area | Lane |
|--------------|-----------|
| Binary / Pwnable | Binary exploitation research |
| Reverse Engineering | Reverse engineering |
| Cryptographic Analysis | Cryptographic analysis |
| Forensics / Artifact Analysis | Artifact analysis |
| Blockchain / Smart Contract | Smart contract research |
| Web Vulnerability Research | Web vulnerability research |
| Container / Cloud | Container and cloud research |

## Research loop

Use this loop to keep research evidence-driven; revisit earlier steps when new facts invalidate the current hypothesis.

- Inventory the target: language, framework, build system, entrypoints, tests, binaries.
- Prove what runs now before trusting comments or stale code.
- Trace untrusted input to sensitive sink before adapting exploit techniques.
- Build the smallest reproducible trigger.
- Confirm impact and constraints.
- Save PoC, logs, crash samples, root-cause notes, and patch suggestions.
- Before completion, write the final Markdown vulnerability research report to `/mnt/project/reports/vulnerability-research-report.md`.

## Evidence layout

```text
/mnt/project/vuln-research/root-cause.md
/mnt/project/vuln-research/poc.py
/mnt/project/vuln-research/repro.sh
/mnt/project/vuln-research/crash.bin
/mnt/project/vuln-research/patch.diff
/mnt/project/reports/vulnerability-research-report.md
```

## Final report requirements

`/mnt/project/reports/vulnerability-research-report.md` must include:

- Target component, version/commit, runtime truth, and assumptions.
- Root cause with source file/line or binary offset when available.
- Input vector, vulnerable sink, and exploitability analysis.
- Minimal PoC/reproducer path and exact reproduction steps.
- Crash logs, traces, request/response, or other decisive evidence.
- Affected versions/prerequisites and confidence/severity.
- Fix direction, patch diff, or mitigation.

## Required fields for a strong finding

- Affected component and version/commit if known.
- Source file and line range.
- Input vector.
- Sink / vulnerable operation.
- Exploitability and prerequisites.
- PoC path or crash artifact.
- Suggested fix or mitigation.

## Lanes

- `vuln_research`: source audit, patch diff, CVE reproduction.
- `ctf_specialist`: pwn/reverse/crypto when challenge-like.
- `triage`: prioritize candidate sinks and reachable paths.
- `report_cleanup`: write root cause and remediation.

## Prefix examples

```text
[cypher:finding type=REPO_FINDING confidence=0.88 severity=high tags=code-audit,path-traversal artifacts=/mnt/project/vuln-research/root-cause.md,/mnt/project/reports/vulnerability-research-report.md cleanup=none] User-controlled `filename` reaches `os.path.join(upload_dir, filename)` without normalization in app/routes.py:88, enabling path traversal.
```

```text
[cypher:finding type=EXPLOIT_RESULT confidence=0.95 severity=critical tags=cve,poc,rce artifacts=/mnt/project/vuln-research/poc.py,/mnt/project/vuln-research/repro.log,/mnt/project/reports/vulnerability-research-report.md cleanup=none] The saved PoC triggers unauthenticated template injection and executes `id` on the vulnerable local service.
```
