# Fase 4 — Promoções e alertas

## Módulos

- `app/services/promotion.py` — detecção de promoções
- `app/alerts/telegram.py` — Telegram opcional + NoOp
- `app/services/monitor.py` — orquestração do ciclo
- `app/scheduler/jobs.py` — APScheduler
- `main.py` — entry do scheduler

## Tipos de alerta

| Tipo | Condição |
|------|----------|
| `new_lowest_price` | Preço < mínimo histórico |
| `discount_vs_average` | Desconto ≥ YAML vs média 30d |
| `abnormal_drop` | Queda ≥ 25% em 24h |
| `new_cheap_listing` | Produto novo abaixo do percentil 20 |

## Resumo de ciclo (fallback)

Se **nenhum** alerta de promoção foi enviado no ciclo:

| Situação | Telegram |
|----------|----------|
| Coletou produtos (`scraped` > 0) | **Menor preço** entre ofertas com preço total &lt; `alerts.fallback_max_price` (padrão: `expected_price_range.max`), mesmo sem passar filtros |
| Salvos com promoção | Menor entre os que **passaram** nos filtros |
| Nada coletado (`scraped` = 0) | Aviso **ciclo sem dados** + resumo por marketplace |

Configure em `config/products.yaml`:

```yaml
alerts:
  fallback_max_price: 6000  # só entra no resumo se preço total < este valor
```

Logs no Actions: bloco `========== CYCLE SUMMARY ==========` e artifact `cycle-log`.

## Telegram

Configure `.env`:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Sem token, alertas são ignorados silenciosamente (log DEBUG).

## Execução

```bash
python main.py
```
