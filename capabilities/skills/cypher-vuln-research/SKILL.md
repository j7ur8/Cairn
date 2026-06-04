---
name: cypher-vuln-research
description: Vulnerability research orchestration skill — delegates source audit, CVE reproduction, PoC adaptation, fuzzing, and root-cause analysis to specialist sub-skills, coordinates evidence collection and research report generation.
version: 0.2.0
---

# Cypher Vulnerability Research Skill (Orchestration Layer)

Use this skill for source-code audit, CVE reproduction, exploit adaptation, binary analysis, fuzzing, or patch-diff research. This skill acts as the **orchestration layer** — it triages the target, delegates to specialist sub-skills, and coordinates root-cause evidence.

## Sub-skill delegation

| Research area | Sub-skill |
|--------------|-----------|
| Binary / Pwnable | `cypher-pwn` |
| Reverse Engineering | `cypher-reverse` |
| Cryptographic Analysis | `cypher-crypto` |
| Forensics / Artifact Analysis | `cypher-forensics` |
| Blockchain / Smart Contract | `cypher-blockchain` |
| Web Vulnerability Research | `cypher-sqli`, `cypher-deserialization`, `cypher-ssti`, `cypher-xxe`, etc. |
| Container / Cloud | `cypher-container`, `cypher-cloud` |

## Core loop

1. Inventory the target: language, framework, build system, entrypoints, tests, binaries.
2. Prove what runs now before trusting comments or stale code.
3. Trace untrusted input to sensitive sink.
4. Build the smallest reproducible trigger.
5. Confirm impact and constraints.
6. Save PoC, logs, crash samples, root-cause notes, and patch suggestions.
7. Before completion, write the final Markdown vulnerability research report to `/mnt/project/reports/vulnerability-research-report.md`.

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
