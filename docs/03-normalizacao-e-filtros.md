# Fase 3 — Normalização, filtros e persistência

## Módulos

- `app/normalization/title.py` — normalização e `ignored_terms`
- `app/services/trust_score.py` — score 0–100 e níveis BAIXA/MÉDIA/ALTA
- `app/database/repository.py` — upsert, histórico, alertas

## Fluxo de filtro

1. `should_ignore_title` — termos de acessórios do YAML
2. `is_relevant_product` — exige Switch 2; remove jogos, Lite, Switch 1, peças (`product.relevance` no YAML)
3. `calculate_trust_score` — anti-golpe
4. Rejeição se `score < trust.minimum_score_to_persist`
5. Persistência em `products` + `price_history`

## Mercado Livre — só nacional

Com `filters.only_national_results: true`:

- URL precisa ser `mercadolivre.com.br` com id `MLB…`
- Cards com “compra internacional”, “envio do exterior”, “versão americana”, etc. são ignorados

## Trust score

Penalidades por preço suspeito, rating, vendas, loja vazia e termos de risco.
