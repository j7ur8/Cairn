#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

export CAIRN_HOST_ROOT
CAIRN_HOST_ROOT=$(pwd)

export CAIRN_DATA_DIR="${CAIRN_DATA_DIR:-./datas}"

prepare_cloak_browser_archive() {
  cloak_version="146.0.7680.177.5"
  cloak_release="chromium-v${cloak_version}"
  cloak_archive="cloakbrowser-linux-x64.tar.gz"
  cloak_cache_dir="capabilities/mcp/js-reverse-mcp/sidecar/.cloak-downloads/${cloak_release}"
  cloak_primary_base="https://cloakbrowser.dev/${cloak_release}"
  cloak_fallback_base="https://github.com/CloakHQ/cloakbrowser/releases/download/${cloak_release}"

  mkdir -p "$cloak_cache_dir"

  download_cloak_file() {
    file_name="$1"
    destination="${cloak_cache_dir}/${file_name}"
    tmp="${destination}.tmp"

    if [ -s "$destination" ]; then
      return 0
    fi

    rm -f "$tmp"
    if curl -fL --retry 3 "${cloak_primary_base}/${file_name}" -o "$tmp"; then
      mv "$tmp" "$destination"
      return 0
    fi

    rm -f "$tmp"
    if curl -fL --retry 3 "${cloak_fallback_base}/${file_name}" -o "$tmp"; then
      mv "$tmp" "$destination"
      return 0
    fi

    rm -f "$tmp"
    echo "Failed to download CloakBrowser ${file_name}" >&2
    return 1
  }

  download_cloak_file "SHA256SUMS"
  download_cloak_file "SHA256SUMS.sig"
  download_cloak_file "$cloak_archive"

  expected_hash=$(
    awk -v name="$cloak_archive" '($2 == name || $2 == "*" name) { print tolower($1); exit }' \
      "${cloak_cache_dir}/SHA256SUMS"
  )
  if [ -z "$expected_hash" ]; then
    echo "SHA256SUMS does not contain ${cloak_archive}" >&2
    return 1
  fi

  if command -v sha256sum >/dev/null 2>&1; then
    actual_hash=$(sha256sum "${cloak_cache_dir}/${cloak_archive}" | awk '{ print tolower($1) }')
  elif command -v shasum >/dev/null 2>&1; then
    actual_hash=$(shasum -a 256 "${cloak_cache_dir}/${cloak_archive}" | awk '{ print tolower($1) }')
  else
    echo "Neither sha256sum nor shasum is available for CloakBrowser archive verification" >&2
    return 1
  fi

  if [ "$actual_hash" != "$expected_hash" ]; then
    echo "CloakBrowser archive checksum mismatch for ${cloak_cache_dir}/${cloak_archive}" >&2
    echo "Expected: $expected_hash" >&2
    echo "Actual:   $actual_hash" >&2
    return 1
  fi
}

prepare_cloak_browser_archive

exec docker compose up -d --build "$@"
