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
