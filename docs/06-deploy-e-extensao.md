# Fase 6 — Deploy e extensão

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

- **scheduler**: scraping automático (`main.py`)
- **dashboard**: http://localhost:8501

## GitHub Actions

Workflow: `.github/workflows/price-monitor.yml`

1. Crie repositório no GitHub e faça push do projeto
2. Em **Settings → Secrets**, adicione:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. O workflow roda a cada 4 horas e executa `run-once`
4. O banco SQLite é cacheado entre runs via `actions/cache`

**Limitações:** 2000 min/mês no plano free; sem dashboard 24/7.

## Oracle Cloud Always Free VPS

Melhor opção para Playwright 24/7 sem limite de minutos do Actions.

### Passos resumidos

1. Criar conta em [Oracle Cloud](https://www.oracle.com/cloud/free/)
2. Criar VM **Ampere A1** (Always Free) — Ubuntu 22.04
3. Abrir porta 8501 no Security List (se usar dashboard)
4. SSH na VM:

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER
# relogar
git clone <seu-repo> motor-pesquisa-preco
cd motor-pesquisa-preco
cp .env.example .env
# editar .env com Telegram
docker compose up -d --build
```

5. Systemd (opcional) para reinício automático:

```ini
# /etc/systemd/system/price-monitor.service
[Unit]
Description=Price Monitor Docker Compose
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ubuntu/motor-pesquisa-preco
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable price-monitor
sudo systemctl start price-monitor
```

## Adicionar novo marketplace

1. Criar `app/scrapers/novo_mp.py` herdando `BaseScraper`
2. Implementar `async def search_products(self, query: str)`
3. Registrar em `app/scrapers/registry.py` (`SCRAPER_CLASSES`)
4. Adicionar flag em `config/products.yaml` → `marketplaces`

## Adicionar novo produto

Edite `config/products.yaml`:

- `main_term`, `search_terms`, `ignored_terms`
- `expected_price_range`, `normalization_rules`

Nenhum código precisa mudar se a categoria for similar.

## Amazon / Kabum

Stubs em `app/scrapers/amazon.py` e `kabum.py`. Ative com `amazon: true` ou `kabum: true` no YAML após implementar o scraper.

## Magazine Luiza

Seguir o mesmo padrão: novo arquivo + registro no `registry.py`.
