#!/usr/bin/env bash
# Um ciclo manual na VPS (healthcheck CDP + run-once no container).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
bash scripts/healthcheck-cdp.sh || echo "AVISO: CDP offline — Shopee usará plano B se SHOPEE_CDP_STRICT=false"
docker compose -f docker-compose.yml -f docker-compose.vps.yml run --rm scheduler \
  python -m app.cli run-once
