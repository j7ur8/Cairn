#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

export CAIRN_HOST_ROOT
CAIRN_HOST_ROOT=$(pwd)

export CAIRN_DATA_DIR="${CAIRN_DATA_DIR:-./datas}"

ids=$(docker ps -aq --filter "label=cairn.managed=true")
if [ -n "$ids" ]; then
  docker rm -f $ids
fi

exec docker compose down --remove-orphans "$@"
