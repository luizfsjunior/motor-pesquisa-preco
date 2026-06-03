# Fase 2 — Scrapers

## Implementação

| Marketplace | Arquivo | Estratégia |
|-------------|---------|------------|
| Shopee | `app/scrapers/shopee.py` | API `v4/search/search_items` → fallback Playwright |
| Mercado Livre | `app/scrapers/mercadolivre.py` | Playwright + paginação + filtro patrocinados |
| Google Shopping | `app/scrapers/google_shopping.py` | `tbm=shop` BR — modo degradado se CAPTCHA |
| Amazon | `app/scrapers/amazon.py` | Stub (desabilitado) |
| Kabum | `app/scrapers/kabum.py` | Stub (desabilitado) |

## Registry

`app/scrapers/registry.py` instancia scrapers conforme `marketplaces` no YAML.

## Teste manual

```bash
playwright install chromium
python -m app.cli run-once
```

## Riscos

- Seletores CSS podem mudar — ajustar queries no scraper correspondente.
- Google pode exibir CAPTCHA — ciclo continua com lista vazia e log WARNING.
