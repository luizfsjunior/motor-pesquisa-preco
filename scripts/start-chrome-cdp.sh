#!/usr/bin/env bash
# Chrome CDP para Shopee (Linux / Oracle VPS). Uso manual ou referência do systemd.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="${SHOPEE_CDP_PROFILE:-$ROOT/data/chrome_cdp_profile}"
PORT="${SHOPEE_CDP_PORT:-9222}"

CHROME=""
for c in google-chrome-stable google-chrome chromium-browser chromium; do
  if command -v "$c" >/dev/null 2>&1; then
    CHROME="$c"
    break
  fi
done
if [[ -z "$CHROME" ]]; then
  echo "Chrome/Chromium não encontrado. Rode: deploy/oracle/install.sh"
  exit 1
fi

mkdir -p "$PROFILE"
if curl -sf "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
  echo "CDP já ativo em http://127.0.0.1:${PORT}"
  exit 0
fi

echo "=== Chrome CDP para Shopee ==="
echo "Perfil: $PROFILE"
echo "Porta:  $PORT"
echo "Login: e-mail/telefone Shopee (NÃO use Google OAuth)"
echo ""

exec "$CHROME" \
  --remote-debugging-port="$PORT" \
  --remote-debugging-address=127.0.0.1 \
  --remote-allow-origins=* \
  --user-data-dir="$PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --disable-dev-shm-usage \
  "https://shopee.com.br/buyer/login"
