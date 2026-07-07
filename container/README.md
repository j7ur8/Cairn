# Cairn Runtime Images

Build the split runtime images from the repository root:

```bash
docker build ./container/runner -t cairn-llm-runner:latest
docker build ./container/tools-kali -t cairn-kali-tools:latest
docker build ./container/tools-metasploit -t cairn-metasploit-tools:latest
```

When starting the full stack with `./start.sh`, Compose builds these tags through the `cairn-runner-image`, `cairn-kali-tools-image`, and `cairn-metasploit-tools-image` helper services.

Runner smoke tests:

```bash
docker run --rm cairn-llm-runner:latest codex --help
docker run --rm cairn-llm-runner:latest claude --help
docker run --rm cairn-llm-runner:latest sh -lc '! command -v sqlmap && ! command -v nmap && ! command -v msfconsole'
```

Kali sidecar smoke tests:

```bash
docker run --rm cairn-kali-tools:latest kali-server-mcp -h
docker run --rm cairn-kali-tools:latest nmap --version
docker run --rm cairn-kali-tools:latest sqlmap --version
```

Metasploit sidecar smoke tests:

```bash
docker run --rm cairn-metasploit-tools:latest msfconsole --version
docker run --rm cairn-metasploit-tools:latest msfrpcd -h
docker run --rm cairn-metasploit-tools:latest metasploitmcp --help
```
