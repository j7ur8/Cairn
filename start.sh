#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

export CAIRN_HOST_ROOT
CAIRN_HOST_ROOT=$(pwd)

export CAIRN_DATA_DIR="${CAIRN_DATA_DIR:-./datas}"

exec docker compose up -d --build "$@"
