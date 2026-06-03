# Motor de Pesquisa de Preços — Multi-Marketplace

Sistema modular em Python para monitoramento automático de preços em marketplaces brasileiros, com foco inicial no **Nintendo Switch 2**.

## Funcionalidades

- Scraping automático (Shopee, Mercado Livre, Google Shopping)
- Comparação entre marketplaces
- Histórico de preços em SQLite
- Detecção de promoções reais
- Anti-golpe (score de confiança)
- Alertas Telegram (opcional)
- Dashboard Streamlit
- Exportação CSV/Excel
- Scheduler APScheduler
- Docker Compose + GitHub Actions + guia Oracle Cloud

## Stack

Python 3.12+, Playwright, SQLAlchemy, SQLite, APScheduler, Streamlit, pandas, pydantic, PyYAML, requests, loguru.

## Instalação

```bash
git clone <repo>
cd motor-pesquisa-preco
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

## Configuração

### `.env`

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
HEADLESS=true
DATABASE_URL=sqlite:///data/prices.db
LOG_LEVEL=INFO
```

Telegram é **opcional**. Sem token, o sistema roda normalmente (sem alertas).

### `config/products.yaml`

Toda a lógica de produto, marketplaces, filtros, alertas e scheduler é configurável via YAML. Veja o arquivo padrão para Nintendo Switch 2.

## Execução

```bash
# Criar banco
python -m app.cli init-db

# Um ciclo de scraping
python -m app.cli run-once

# Scheduler contínuo
python main.py

# Dashboard
streamlit run app/dashboard/app.py
```

## Docker

```bash
cp .env.example .env
docker compose up --build
```

- Scheduler: scraping em background
- Dashboard: http://localhost:8501

## Bot Telegram

1. Abra [@BotFather](https://t.me/BotFather) no Telegram
2. `/newbot` → copie o token para `TELEGRAM_BOT_TOKEN`
3. Envie uma mensagem ao bot
4. Acesse `https://api.telegram.org/bot<TOKEN>/getUpdates` e copie o `chat.id` para `TELEGRAM_CHAT_ID`

## Arquitetura

```
config/products.yaml → PriceMonitorService
    → Scrapers (BaseScraper)
    → Normalização + Trust Score
    → SQLite (products, price_history)
    → PromotionService → Telegram (opcional)
```

### Adicionar marketplace

1. Herde `BaseScraper` em `app/scrapers/`
2. Registre em `app/scrapers/registry.py`
3. Ative em `config/products.yaml`

Documentação detalhada por fase em `docs/01-fundacao.md` … `docs/06-deploy-e-extensao.md`.

## GitHub Actions

Configure secrets `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`. O workflow em `.github/workflows/price-monitor.yml` executa scraping a cada 15 minutos.

## Hospedagem 24/7

Para Playwright contínuo, use **Oracle Cloud Always Free VPS** com Docker Compose — guia em [docs/06-deploy-e-extensao.md](docs/06-deploy-e-extensao.md).

## Estrutura

```
app/
├── scrapers/      # Shopee, ML, Google, stubs Amazon/Kabum
├── database/      # SQLAlchemy session + repository
├── models/        # ORM + Pydantic schemas
├── normalization/
├── services/      # monitor, promotion, trust_score
├── alerts/        # Telegram
├── dashboard/     # Streamlit
├── scheduler/
├── config/
└── utils/
config/products.yaml
data/  logs/  exports/
main.py
```

## Troubleshooting

| Problema | Solução |
|----------|---------|
| Playwright não encontrado | `playwright install chromium` |
| Google sem resultados | CAPTCHA — normal em CI; tente local |
| Shopee vazio | API pode bloquear; fallback HTML ativo |
| DB vazio | Aguarde `run-once` ou verifique logs em `logs/` |

## Licença

Uso interno / projeto pessoal.
