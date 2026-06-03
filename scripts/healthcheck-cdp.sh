#!/usr/bin/env bash
set -euo pipefail
PORT="${SHOPEE_CDP_PORT:-9222}"
URL="http://127.0.0.1:${PORT}/json/version"
if curl -sf "$URL" >/dev/null; then
  echo "OK CDP $URL"
  exit 0
fi
echo "OFFLINE CDP $URL — inicie: sudo systemctl start chrome-cdp"
exit 1
