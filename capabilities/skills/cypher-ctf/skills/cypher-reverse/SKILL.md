---
name: cypher-reverse
description: Reverse engineering methodology covering static analysis (Ghidra/IDA/radare2), dynamic debugging (gdb/lldb/x64dbg), deobfuscation, unpacking, anti-debug bypass, and symbol recovery for ELF/PE/Mach-O targets.
version: 0.1.0
finding_types: [BINARY_FINDING, EXPLOIT_PRIMITIVE, REPO_FINDING, BLOCKER]
destructiveness: low
tags: [ctf, reverse, disassembly, deobfuscation, unpacking]
---

# Cypher Reverse Engineering Skill

Use this skill for CTF reverse challenges, malware analysis, binary auditing, and understanding compiled/protected code.

## Initial triage

```bash
file ./binary                 # ELF/PE/Mach-O, 32/64-bit, static/dynamic, stripped
strings ./binary              # Quick win: embedded URLs, flags, error messages
strings -n 10 ./binary        # Longer strings only
rabin2 -I ./binary            # radare2: binary info (arch, bits, canary, NX, PIE)
readelf -h ./binary           # ELF header: entry point, sections
nm ./binary 2>/dev/null       # Symbols (if not stripped)
ldd ./binary                  # Shared libraries (be careful — can execute binary)
objdump -t ./binary           # Symbol table (if not stripped)
```

## Static analysis

### Ghidra (preferred for complex binaries)
1. Create project → import binary → analyze with default analyzers.
2. Find `entry` → trace to `main` (or `__libc_start_main` arg).
3. Rename functions, variables, and parameters as you understand them.
4. Use "Find References" to trace where a variable or function is used.
5. Export decompiled code for documentation.

### IDA Free / Pro
1. Load binary → auto-analysis.
2. Use Graph View for control flow understanding.
3. `Shift+F12` — open Strings window.
4. `X` — cross-references (xrefs) to/from a location.
5. `N` — rename symbol.
6. IDAPython for automation: `idc.get_wide_dword()`, `idc.get_func_name()`, etc.

### radare2 / rizin
```bash
r2 ./binary
aaa                 # auto-analyze
afl                 # list functions
pdf @main           # disassemble main function
izz                 # list strings
axt <addr>          # cross-references to address
pf <format> @<addr> # print formatted data
```

### Binary Ninja
- Medium-level IL (MLIL) and High-level IL (HLIL) are often cleaner than raw disassembly.
- Use HLIL for quick understanding of complex functions.

## Common CTF reverse patterns

### Flag comparisons
- `strcmp(input, flag)` → breakpoint on strcmp, read arguments
- `memcmp(input, computed, len)` → breakpoint on memcmp
- Custom comparison: XOR with key, then compare → extract key, reverse XOR
- Timing-based: compare one char at a time, early exit on wrong char → side-channel brute-force

### Obfuscation techniques
| Technique | Recognition | Bypass |
|-----------|------------|--------|
| XOR string encoding | Repeated XOR loops with a key byte | Extract key, decode all strings |
| Control flow flattening | Giant switch/dispatcher with state var | Trace state transitions, recover original flow |
| Opaque predicates | Branches that always go one way | Simplify in decompiler, pattern match |
| Dead code insertion | Never-executed basic blocks | Dead code elimination |
| Instruction substitution | `push/pop` instead of `mov`, `lea` abuse | Pattern recognition, peephole optimization |
| Anti-disassembly | Overlapping instructions, jump into middle of instruction | Fix up in disassembler, nop out junk bytes |

### Unpacking
```bash
# UPX
upx -d ./binary

# Other packers: detect with Detect It Easy (DIE) or PEiD
# Manual unpacking:
# 1. Let packer run, break on OEP (original entry point)
# 2. Dump memory: gdb> dump memory dump.bin <start> <end>
# 3. Reconstruct IAT (Import Address Table) with Scylla/ImportREC
```

## Dynamic analysis

### gdb (GEF / pwndbg recommended)
```gdb
gdb -q ./binary
b *main                  # breakpoint at main
b *0x401234              # breakpoint at address
r                        # run
c                        # continue
ni                       # next instruction (step over)
si                       # step instruction (step into)
x/s $rdi                 # examine string at rdi
x/10gx $rsp              # examine 10 giant words at stack pointer
info registers           # dump registers
watch *0x601018          # hardware watchpoint
set $rax=0               # modify register
```

### Tracing
```bash
strace ./binary           # syscall trace
ltrace ./binary           # library call trace (won't work on statically linked)
```

### Patching
- NOP out anti-debug checks: replace bytes with `0x90` (x86) or `1f 20 03 d5` (ARM64)
- Change conditional jumps: `jne` → `je` (0x85 → 0x84), `jle` → `jg` (0x7E → 0x7F)
- Return 1 from check functions: `mov eax, 1; ret` → `b8 01 00 00 00 c3`
- `printf("%s", flag)` instead of `printf("Wrong!")`: change format string pointer

## Language-specific reverse

### Python (pyc/pyo)
- **uncompyle6 / decompyle3**: `uncompyle6 file.pyc`
- **pycdc**: Alternative decompiler
- **pyinstxtractor + uncompyle6**: PyInstaller-packed executables

### Java (JAR/class)
- **JD-GUI / jadx**: Decompile `.class` → Java source
- **Procyon / CFR**: Alternative Java decompilers
- **bytecode-viewer**: Multi-decompiler comparison
- Obfuscated: **DeGuard**, manual trace with `java -verbose:class`

### .NET (C#)
- **dnSpy**: Decompile, debug, and modify .NET assemblies
- **ILSpy**: Open-source decompiler
- **de4dot**: Deobfuscator for common .NET protectors

### JavaScript
- See `hello-js-reverse` skill for browser-based JS reverse
- Node.js: `node --inspect-brk`, Chrome DevTools
- Obfuscated: **synchrony**, **JS Nice**, **webcrack**

### Go
- `go tool objdump ./binary`
- Strings from Go binaries: embedded symbol table even in stripped builds
- **go_parser** (Ghidra plugin) or **golang_loader_assist** (IDA)
- Interface method dispatch: look up itab/vtable

## Evidence rules

- Save the annotated disassembly/decompilation to `/mnt/project/vuln-research/annotated-binary/`.
- Save any extracted/deobfuscated code to `/mnt/project/exploit/extracted/`.
- If the challenge involves generating a flag/key, save the solver script to `/mnt/project/exploit/solve.py`.
- Document: binary type/protections, obfuscation techniques encountered, analysis path, and final flag/key derivation.

## Prefix examples

```text
[cypher:finding type=BINARY_FINDING confidence=0.9 severity=info tags=ctf,reverse,obfuscated artifacts=/mnt/project/vuln-research/annotated-binary/main-decompiled.c cleanup=none] Main validation function identified at 0x401200. Flag is XOR'd with 0x37 and compared to a hardcoded byte array — key extraction in progress.
```

```text
[cypher:finding type=EXPLOIT_RESULT confidence=1.0 severity=info tags=ctf,reverse artifacts=/mnt/project/exploit/solve.py cleanup=none] Recovered flag{unp4ck_4nd_x0r_2_win} via dynamic analysis: extracted XOR key from .rodata at 0x403000, decoded the comparison array.
```
