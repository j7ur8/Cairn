# Vulnerability Research Report

**Target:** {component_name} {version}
**Researcher:** Cypher Agent
**Date:** {date}
**CVE:** {cve_id or "New Discovery"}

---

## Executive Summary

[Brief: target component, vulnerability type, impact, exploitability, and confidence]

---

## Target Information

| Attribute | Value |
|-----------|-------|
| **Component** | |
| **Version / Commit** | |
| **Language / Runtime** | |
| **Build System** | |
| **Repository** | |
| **Vulnerability Type** | CWE-XXX |
| **Severity** | Critical / High / Medium / Low |
| **CVSS 3.1** | X.X |

---

## Root Cause Analysis

### Affected Code

**File:** `path/to/file.ext:line_range`

```c
// Vulnerable code snippet
```

### Input Vector

[How untrusted input reaches the vulnerability]

### Sink / Vulnerable Operation

[The exact operation that is abused]

### Trace

```
[Call stack or data flow trace from entrypoint to sink]
```

---

## Proof of Concept

### Minimal Reproducer

**Path:** `/mnt/project/vuln-research/poc.py`

```python
# Minimal PoC code
```

### Reproduction Steps

1. [Environment setup]
2. [Build/compile if needed]
3. [Run the PoC]

### Expected vs Actual Behavior

- **Expected:** [Normal behavior]
- **Actual:** [Exploited behavior showing impact]

### Output / Crash

```
[Crash log, exploit output, or verification evidence]
```

---

## Exploitability Analysis

### Prerequisites
- [Required conditions: authentication, configuration, platform]

### Constraints
- [Limitations: ASLR, compiler flags, runtime protections]

### Reliability
- [Probability of successful exploitation, races, brute-force requirements]

### Impact
- [What the exploit can achieve: RCE, information disclosure, DoS, privilege escalation]

---

## Affected Versions

| Version | Status |
|---------|--------|
| < X.Y.Z | Vulnerable |
| X.Y.Z+ | Patched |

### Detection Guidance

- [How to detect vulnerable instances: banners, response patterns, static signatures]

---

## Fix / Mitigation

### Patch

```diff
// patch.diff showing the fix
```

### Workaround

[If a patch is not available]

---

## Evidence Files

- `/mnt/project/vuln-research/root-cause.md` — Detailed analysis
- `/mnt/project/vuln-research/poc.py` — PoC/reproducer
- `/mnt/project/vuln-research/repro.sh` — Reproduction script
- `/mnt/project/vuln-research/crash.bin` — Crash sample (if applicable)
- `/mnt/project/vuln-research/patch.diff` — Suggested patch

---

## References

- [CVE references, blog posts, related research]
