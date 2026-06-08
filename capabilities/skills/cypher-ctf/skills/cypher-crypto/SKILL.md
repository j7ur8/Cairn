---
name: cypher-crypto
description: Cryptography challenge methodology covering classical ciphers, symmetric/asymmetric cryptanalysis, hash length extension, padding oracle attacks, RSA vulnerabilities (small e, Wiener, Coppersmith), ECC, PRNG prediction, and side-channel reasoning.
version: 0.1.0
finding_types: [CRYPTO_FINDING, VULN_CANDIDATE, EXPLOIT_RESULT]
destructiveness: low
tags: [ctf, crypto, rsa, aes, ecc, oracle]
---

# Cypher Cryptography Skill

Use this skill for CTF crypto challenges, cryptographic vulnerability research, and protocol-level crypto analysis.

## Initial triage

1. Read the challenge files: source code, public keys, ciphertexts, captured traffic.
2. Identify the cryptographic primitives used: cipher type, key size, mode of operation, padding scheme.
3. Check for classic implementation flaws: nonce reuse, weak random, textbook RSA, short padding.
4. Determine if the vulnerability is in the algorithm (weak params), the implementation (side-channel, bug), or the protocol (replay, oracle).

## Classical ciphers

### Substitution / Transposition
```bash
# Frequency analysis
cat ciphertext | fold -w1 | sort | uniq -c | sort -rn
# Online tools: dcode.fr, quipqiup.com, boxentriq.com
# CyberChef: "Magic" recipe for automated detection
```

### XOR ciphers
- Single-byte XOR: brute-force 256 keys, score by English letter frequency (Chi-squared or Bhattacharyya)
- Multi-byte XOR (Vigenère): Kasiski examination, Friedman test for key length, then per-offset single-byte XOR
- Known plaintext attack: `ciphertext ⊕ plaintext = key` → apply key to rest

### Base encodings
- Multi-layer base64/base32/base85: decode recursively
- Base64 with custom alphabet: identify character set, map to standard, decode
- Base64 URL-safe (`-_` instead of `+/`): adjust alphabet

## Symmetric cryptography

### ECB mode
- **Codebook attack**: Identical plaintext blocks → identical ciphertext blocks. Submit known block patterns to build a codebook.
- **Block shuffling**: Reorder ciphertext blocks → plaintext blocks reorder correspondingly (no integrity check).
- **Cut-and-paste**: Take ciphertext blocks from one message and splice into another.

### CBC mode
- **IV manipulation**: Changing IV byte X changes plaintext byte X of the first block by the same XOR difference.
- **Bit flipping**: Flip a bit in ciphertext block N → flips corresponding bit in plaintext block N+1 (and garbles block N).
- **Padding oracle attack** (see dedicated section below).

### CTR / GCM mode
- **Nonce reuse**: C1 ⊕ C2 = P1 ⊕ P2 (XOR cancels key stream). If one plaintext is known or guessable, the other is recovered.
- **GCM authentication bypass**: Reuse nonce → recover auth key H → forge authentication tags.

### Stream ciphers (RC4, ChaCha20)
- **Key stream reuse**: Same as CTR nonce reuse.
- **RC4 biases**: Early bytes biased (FMS attack, WEP cracking).
- **ChaCha20**: No known practical attacks when used correctly; check for nonce reuse.

## Padding oracle attack

When the server returns distinguishable errors for valid vs invalid padding (PKCS#7):

```python
from pwn import *
# Core concept:
# PKCS#7 padding: if 1 byte of padding → pad byte is 0x01
#                  if 16 bytes of padding → pad bytes are 0x10 each
# Oracle: send (IV || ciphertext_block), server says "padding OK" or "padding ERROR"
# For each byte position in the intermediate state:
#   Try all 256 values for the corresponding IV byte
#   When padding is valid → intermediate_byte XOR IV_byte = desired_pad_value
#   → intermediate_byte = desired_pad_value XOR IV_byte
#   → plaintext_byte = original_IV_byte XOR intermediate_byte
```

Tools: **padbuster**, **padding-oracle-attacker** (Python), **poracle** (Ruby).

## RSA attacks

### Small e (e=3, low exponent)
- If `m^e < N` (no modular reduction): `m = pow(c, 1/e)` (cube root, no modular arithmetic)
- Broadcast attack (Hastad): same message encrypted with e=3 under different N1, N2, N3 → CRT recovery

### Wiener attack (small d)
- When `d < N^0.25 / 3`, Wiener's continued fraction attack recovers d
- **owiener** (Python): `d = owiener.attack(e, n)`
- Common in CTF when e is unusually large (e ≈ N)

### Boneh-Durfee attack (d < N^0.292)
- Extension of Wiener for larger d
- SageMath implementation

### Common factor attack
- Multiple moduli share a prime factor: `gcd(N1, N2)` recovers p
- Batch GCD: `python3 -c "from math import gcd; from itertools import combinations; ..."`

### Factor with known bits
- Coppersmith's method: recover full p when partial bits are known
- SageMath: `small_roots()` on polynomial `(p_high + x)(q_high + y) = N`

### Bleichenbacher attack (PKCS#1 v1.5)
- Padding oracle on RSA encryption: chosen ciphertext → server says "valid PKCS#1 v1.5 padding"
- Tool: **ROCA** (Return Of Coppersmith Attack) for weak RSA key generation

### Common modulus attack
- Same message encrypted with different e under same N: if `gcd(e1, e2) = 1`, extended GCD recovers plaintext

## ECC attacks

- **Small subgroup attack**: Send point in small-order subgroup → recover key bits via discrete log in small subgroup
- **Invalid curve attack**: Point is not on the curve → server uses custom curve params → transfer to weak curve
- **Pohlig-Hellman**: ECDLP when order is smooth (small prime factors)

## Hash attacks

### Hash length extension
- MD5, SHA-1, SHA-256, SHA-512 (Merkle-Damgård constructions) are vulnerable
- Given `H(secret || message)` and `len(secret)`, compute `H(secret || message || padding || append)` without knowing the secret
- Tool: **hash_extender**, **hashpump**

### Collision
- MD5 collisions: **fastcoll**, **hashclash**
- SHA-1: SHAttered, chosen-prefix collisions (expensive but demonstrated)

## PRNG attacks

- **LCG (Linear Congruential Generator)**: Recover modulus, multiplier, increment from observed outputs → predict all future outputs
- **MT19937 (Mersenne Twister)**: 624 consecutive 32-bit outputs → full state recovery → predict all future outputs
- **Java Random**: LCG → two consecutive `nextInt()` values recover state
- Seed-based: if seed is small (timestamp, PID), brute-force seed space

## Tools reference

| Category | Tools |
|----------|-------|
| General | CyberChef, dcode.fr, SageMath, pwntools |
| RSA | RsaCtfTool, owiener, factordb.com, Alpertron ECM |
| ECDLP | SageMath `discrete_log()`, ecpy, Pohlig-Hellman in Sage |
| Hash | hashcat, john, hash_extender, hashpump, hash-identifier |
| Classical | quipqiup, boxentriq, dcode.fr cipher identifier |
| Coppersmith | SageMath `small_roots()`, defund/coppersmith |

## Evidence rules

- Save the solver script to `/mnt/project/exploit/solve.py` (or `.sage` for SageMath).
- Save intermediate findings (factored N, recovered key, decrypted ciphertext) to `/mnt/project/vuln-research/`.
- Document the vulnerability (e.g., "RSA e=3 cube-root attack", "CBC padding oracle"), the attack method, and the recovered plaintext/flag.

## Prefix examples

```text
[cypher:finding type=CRYPTO_FINDING confidence=0.9 severity=medium tags=ctf,crypto,rsa artifacts=/mnt/project/vuln-research/rsa-analysis.txt cleanup=none] RSA 2048-bit with e=3 — cube-root attack viable since m^e < N. Ciphertext extracted from challenge.pem.
```

```text
[cypher:finding type=EXPLOIT_RESULT confidence=1.0 severity=info tags=ctf,crypto,padding-oracle artifacts=/mnt/project/exploit/solve.py cleanup=none] CBC padding oracle on /api/decrypt recovered session cookie plaintext — flag{0racl3_kn0ws_y0ur_p4dding}.
```
