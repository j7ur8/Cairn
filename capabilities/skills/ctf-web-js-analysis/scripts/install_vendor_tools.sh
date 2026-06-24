#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$ROOT/tools/vendor"

install_node() {
  local dir="$1"
  if [[ -f "$dir/package-lock.json" ]]; then
    (cd "$dir" && npm ci)
  elif [[ -f "$dir/package.json" ]]; then
    (cd "$dir" && npm install)
  fi
}

install_python() {
  local dir="$1"
  if [[ -f "$dir/requirements.txt" ]]; then
    python3 -m pip install -r "$dir/requirements.txt"
  fi
}

build_go() {
  local dir="$1"
  if [[ -f "$dir/go.mod" ]]; then
    (cd "$dir" && go mod download && go build ./...)
  fi
}

for dir in "$VENDOR"/*; do
  [[ -d "$dir" ]] || continue
  echo "[*] preparing $(basename "$dir")"
  install_node "$dir"
  install_python "$dir"
  build_go "$dir"
done
