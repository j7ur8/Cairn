#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "[1/3] Running Python test suite"
uv run --project cairn python -m unittest discover -s cairn/tests

echo "[2/3] Building and starting Docker stack"
docker compose up --build -d

echo "[3/3] Waiting for Cairn health endpoints"
for attempt in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

curl -fsS http://127.0.0.1:8000/health >/dev/null

echo "Cairn server is healthy at http://127.0.0.1:8000"
echo "Next step: run browser regression with host Chrome remote debugging and chrome-devtools MCP."
