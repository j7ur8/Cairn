#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"
export CAIRN_CLOAK_SLOTS="${CAIRN_CLOAK_SLOTS:-2}"
export CAIRN_CLOAK_CDP_BASE_PORT="${CAIRN_CLOAK_CDP_BASE_PORT:-9222}"
export CAIRN_CLOAK_CONTROL_PORT="${CAIRN_CLOAK_CONTROL_PORT:-7310}"
export CAIRN_CLOAK_NOVNC_PORT="${CAIRN_CLOAK_NOVNC_PORT:-6080}"

mkdir -p /profiles /tmp/.X11-unix

Xvfb "$DISPLAY" -screen 0 1440x1000x24 -nolisten tcp &
XVFB_PID=$!
fluxbox >/tmp/fluxbox.log 2>&1 &
FLUXBOX_PID=$!
x11vnc -display "$DISPLAY" -forever -shared -nopw -listen 0.0.0.0 -rfbport 5900 >/tmp/x11vnc.log 2>&1 &
X11VNC_PID=$!
websockify --web=/usr/share/novnc/ 0.0.0.0:"$CAIRN_CLOAK_NOVNC_PORT" localhost:5900 >/tmp/novnc.log 2>&1 &
NOVNC_PID=$!

cleanup() {
  kill "$NOVNC_PID" "$X11VNC_PID" "$FLUXBOX_PID" "$XVFB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

exec node /opt/cairn-cloak/control-server.mjs
