# Cairn Worker Container

Build locally:

```bash
docker build . -t cairn-worker-container
```

Build from the repository root with a test tag:

```bash
docker build ./container -t cairn-worker-container:mcp-camoufox
```

When starting the full stack with `./start.sh` from the repository root, Compose builds the same `cairn-worker-container:mcp-camoufox` tag automatically via the `cairn-worker-image` helper service. The manual build command remains useful for isolated image debugging and smoke tests.

Smoke tests:

```bash
docker run --rm cairn-worker-container:mcp-camoufox python3 -c "import camoufox; print('camoufox ok')"
docker run --rm cairn-worker-container:mcp-camoufox kali-server-mcp -h
docker run --rm cairn-worker-container:mcp-camoufox mcp-server -h
docker run --rm cairn-worker-container:mcp-camoufox metasploitmcp --help
docker run --rm cairn-worker-container:mcp-camoufox metasploit-mcp-stdio --help
```

Camoufox headless smoke:

```bash
docker run --rm cairn-worker-container:mcp-camoufox python3 - <<'PY'
from camoufox.sync_api import Camoufox
with Camoufox(headless=True) as browser:
    page = browser.new_page()
    page.goto("data:text/html,<title>ok</title>")
    print(page.title())
PY
```

MCP wrappers installed in the image:

- `/usr/local/bin/kali-mcp-stdio`
- `/usr/local/bin/metasploit-mcp-stdio`
