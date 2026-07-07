#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"
export CAIRN_CLOAK_SLOTS="${CAIRN_CLOAK_SLOTS:-2}"
export CAIRN_CLOAK_CDP_BASE_PORT="${CAIRN_CLOAK_CDP_BASE_PORT:-9222}"
export CAIRN_CLOAK_CONTROL_PORT="${CAIRN_CLOAK_CONTROL_PORT:-7310}"
export CAIRN_CLOAK_NOVNC_PORT="${CAIRN_CLOAK_NOVNC_PORT:-6080}"

mkdir -p /profiles /tmp/.X11-unix

Xvfb "$DISPLAY" -screen 0 1440x1000x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!

display_number="${DISPLAY#:}"
display_number="${display_number%%.*}"
display_socket="/tmp/.X11-unix/X${display_number}"
for _ in $(seq 1 50); do
  if [ -S "$display_socket" ]; then
    break
  fi
  if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    echo "Xvfb exited before ${display_socket} became ready" >&2
    cat /tmp/xvfb.log >&2 2>/dev/null || true
    exit 1
  fi
  sleep 0.1
done
if [ ! -S "$display_socket" ]; then
  echo "Xvfb did not create ${display_socket}" >&2
  exit 1
fi

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
