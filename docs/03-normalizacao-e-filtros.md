# Fase 3 — Normalização, filtros e persistência

## Módulos

- `app/normalization/title.py` — normalização e `ignored_terms`
- `app/services/trust_score.py` — score 0–100 e níveis BAIXA/MÉDIA/ALTA
- `app/database/repository.py` — upsert, histórico, alertas

## Fluxo de filtro

1. `should_ignore_title` — termos de acessórios do YAML
2. `calculate_trust_score` — anti-golpe
3. Rejeição se `score < trust.minimum_score_to_persist`
4. Persistência em `products` + `price_history`

## Trust score

Penalidades por preço suspeito, rating, vendas, loja vazia e termos de risco.
