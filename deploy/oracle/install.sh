#!/usr/bin/env bash
# Instalação automatizada — Oracle Cloud (ou Ubuntu 22.04+) com Chrome CDP 24/7 + Docker.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Rode com sudo: sudo bash deploy/oracle/install.sh"
  exit 1
fi

DEPLOY_USER="${SUDO_USER:-ubuntu}"
WORKDIR="${WORKDIR:-/home/${DEPLOY_USER}/motor-pesquisa-preco}"

echo "==> Pacotes base"
apt-get update -qq
apt-get install -y -qq curl ca-certificates gnupg jq unzip

echo "==> Google Chrome"
if ! command -v google-chrome-stable >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg
  echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list
  apt-get update -qq
  apt-get install -y -qq google-chrome-stable
fi

echo "==> Docker"
if ! command -v docker >/dev/null 2>&1; then
  apt-get install -y -qq docker.io docker-compose-plugin
  systemctl enable --now docker
  usermod -aG docker "$DEPLOY_USER"
fi

if [[ ! -d "$WORKDIR" ]]; then
  echo "ERRO: clone o repo em $WORKDIR antes (git clone ...)."
  exit 1
fi

chown -R "$DEPLOY_USER:$DEPLOY_USER" "$WORKDIR"
chmod +x "$WORKDIR/scripts/"*.sh 2>/dev/null || true

echo "==> systemd chrome-cdp"
CDP_UNIT="/etc/systemd/system/chrome-cdp.service"
sed -e "s|%USER%|${DEPLOY_USER}|g" \
    -e "s|%WORKDIR%|${WORKDIR}|g" \
    "$WORKDIR/deploy/oracle/chrome-cdp.service" > "$CDP_UNIT"
systemctl daemon-reload
systemctl enable chrome-cdp

echo "==> .env VPS (se não existir)"
ENV_FILE="$WORKDIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$WORKDIR/deploy/oracle/env.vps.example" "$ENV_FILE"
  chown "$DEPLOY_USER:$DEPLOY_USER" "$ENV_FILE"
  echo "Edite $ENV_FILE com TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID"
fi

echo "==> Docker Compose VPS"
sudo -u "$DEPLOY_USER" bash -c "cd '$WORKDIR' && docker compose -f docker-compose.yml -f docker-compose.vps.yml build"

cat <<EOF

================================================================================
 Instalação base concluída.

 PRÓXIMOS PASSOS (uma vez):

 1) Login Shopee no Chrome CDP:
      sudo systemctl start chrome-cdp
      # Se a VM não tem tela, use VNC ou copie o perfil do PC:
      #   data/chrome_cdp_profile  (Windows) -> $WORKDIR/data/chrome_cdp_profile

 2) Confirme CDP:
      bash $WORKDIR/scripts/healthcheck-cdp.sh

 3) Edite Telegram:
      nano $WORKDIR/.env

 4) Suba o monitor:
      cd $WORKDIR && docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d

 5) Teste um ciclo:
      docker compose -f docker-compose.yml -f docker-compose.vps.yml run --rm scheduler \\
        python -m app.cli run-once

 Logs: $WORKDIR/logs  |  Chrome: systemctl status chrome-cdp
================================================================================
EOF
