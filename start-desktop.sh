#!/bin/sh
set -eu

mkdir -p /data/auth /data/gflow /data/outputs /tmp/fluxbox

vnc_password_file=/data/auth/.vnc-passwd
if [ ! -f "$vnc_password_file" ]; then
  x11vnc -storepasswd "${NOVNC_PASSWORD:-gemini-flow}" "$vnc_password_file" >/dev/null
  chmod 600 "$vnc_password_file"
fi

Xvfb :99 -screen 0 1440x1000x24 -ac +extension GLX +render -noreset &
xvfb_pid=$!

fluxbox -display :99 >/tmp/fluxbox.log 2>&1 &
fluxbox_pid=$!

x11vnc -display :99 -forever -shared -rfbport 5900 -rfbauth "$vnc_password_file" \
  -o /tmp/x11vnc.log &
vnc_pid=$!

websockify --web=/usr/share/novnc/ 7900 localhost:5900 >/tmp/novnc.log 2>&1 &
novnc_pid=$!

cleanup() {
  kill "$novnc_pid" "$vnc_pid" "$fluxbox_pid" "$xvfb_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

while kill -0 "$xvfb_pid" 2>/dev/null \
  && kill -0 "$vnc_pid" 2>/dev/null \
  && kill -0 "$novnc_pid" 2>/dev/null; do
  sleep 5
done

exit 1
