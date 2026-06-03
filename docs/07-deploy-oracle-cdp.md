# Deploy Oracle VPS — Chrome CDP 24/7 + plano B

## Visão geral

| Ambiente | Shopee | Mercado Livre |
|----------|--------|---------------|
| **PC (Windows)** | `scripts/start-chrome-cdp.bat` + `.env` CDP | Sim |
| **Oracle VPS** | Chrome `systemd` + Docker `docker-compose.vps.yml` | Sim |
| **GitHub Actions** | Plano B: `SHOPEE_FALLBACK_ONLY=true` (DDG+enrich) | Sim |

## Opção 3 — Oracle VPS (automático)

### 1. Criar VM

- [Oracle Cloud Free](https://www.oracle.com/cloud/free/) → Ubuntu 22.04 (Ampere A1)
- Abrir SSH (22); opcional 8501 para dashboard

### 2. Instalar (uma vez)

```bash
git clone <seu-repo> motor-pesquisa-preco
cd motor-pesquisa-preco
sudo WORKDIR=$(pwd) bash deploy/oracle/install.sh
```

### 3. Login Shopee (uma vez)

**A)** Copiar perfil do Windows (recomendado):

```powershell
# No PC, com CDP já logado, feche o Chrome CDP e compacte:
Compress-Archive -Path data\chrome_cdp_profile -DestinationPath chrome_profile.zip
scp chrome_profile.zip ubuntu@<IP-VPS>:~/
```

```bash
# Na VPS:
cd ~/motor-pesquisa-preco
unzip -o ~/chrome_profile.zip -d data/
sudo systemctl restart chrome-cdp
```

**B)** VNC na VPS: instale `tightvncserver` + `systemctl start chrome-cdp`, login manual em `shopee.com.br`.

### 4. Configurar Telegram

```bash
nano .env   # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

Use `deploy/oracle/env.vps.example` como referência.

### 5. Subir serviços

```bash
sudo systemctl start chrome-cdp
bash scripts/healthcheck-cdp.sh
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d
```

### 6. Testar

```bash
docker compose -f docker-compose.yml -f docker-compose.vps.yml run --rm scheduler \
  python -m app.cli run-once
```

### Manutenção

```bash
sudo systemctl status chrome-cdp
docker compose -f docker-compose.yml -f docker-compose.vps.yml logs -f scheduler
python -m app.cli shopee-cdp-check   # dentro do container ou venv local
```

Se o IP da VPS levar captcha permanente, o motor cai no **plano B** (`SHOPEE_CDP_STRICT=false`).

---

## Opção 4 — GitHub Actions (plano B)

Workflow já define:

- `SHOPEE_FALLBACK_ONLY=true` — só DuckDuckGo/Bing/Google + enrich
- Sem CDP

Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

Limitação: ~7 links Shopee por ciclo; ML continua completo.

---

## Arquivos de deploy

| Arquivo | Função |
|---------|--------|
| `deploy/oracle/install.sh` | Instala Chrome, Docker, systemd |
| `deploy/oracle/chrome-cdp.service` | Chrome 24/7 na porta 9222 |
| `scripts/start-chrome-cdp.sh` | Inicia Chrome CDP (Linux) |
| `scripts/healthcheck-cdp.sh` | Verifica CDP antes do cron |
| `docker-compose.vps.yml` | `host.docker.internal:9222` |
| `deploy/oracle/env.vps.example` | Template `.env` VPS |
