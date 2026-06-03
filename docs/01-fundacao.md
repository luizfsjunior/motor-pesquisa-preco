# Fase 1 — Fundação

## Entregáveis

- Estrutura de pastas `app/`, `config/`, `data/`, `logs/`, `exports/`
- `requirements.txt` com stack obrigatória
- `.env.example` com variáveis de ambiente
- `config/products.yaml` — configuração Nintendo Switch 2
- Pydantic Settings (`app/config/settings.py`)
- Loader YAML (`app/config/loader.py`)
- Modelos ORM SQLite (`app/models/orm.py`)
- Schemas Pydantic (`app/models/schemas.py`)
- Sessão SQLAlchemy + `init_db()` (`app/database/session.py`)
- Loguru (`app/utils/logging_setup.py`)

## Como validar

```bash
cd motor-pesquisa-preco
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m app.cli init-db
```

## Próxima fase

Scrapers Playwright para Shopee, Mercado Livre e Google Shopping.
