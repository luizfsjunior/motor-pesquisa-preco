# Fase 5 — Dashboard e exportação

## Dashboard Streamlit

```bash
streamlit run app/dashboard/app.py
```

Ou via Docker: `http://localhost:8501`

### Funcionalidades

- KPIs: menor preço, média, produtos rastreados, última coleta
- Gráfico de linha: evolução por marketplace
- Gráfico de barras: comparação atual
- Ranking de lojas
- Promoções recentes (tabela `alerts_sent`)
- Tabela pesquisável com links
- Exportação CSV/Excel

## Exportação CLI

```bash
python -m app.cli export-csv
python -m app.cli export-excel
```

Arquivos em `exports/`.
