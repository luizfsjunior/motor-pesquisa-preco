from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import select

from app.config.loader import load_app_config
from app.database.session import get_session, init_db
from app.models.orm import AlertSent, PriceHistory, Product
from app.utils.export import export_csv, export_excel

st.set_page_config(
    page_title="Monitor de Preços — Switch 2",
    page_icon="🎮",
    layout="wide",
)

MARKETPLACE_LABELS = {
    "shopee": "Shopee",
    "mercadolivre": "Mercado Livre",
    "google_shopping": "Google Shopping",
    "amazon": "Amazon",
    "kabum": "Kabum",
}


@st.cache_data(ttl=120)
def load_price_data() -> pd.DataFrame:
    init_db()
    rows: list[dict] = []
    with get_session() as session:
        products = session.scalars(select(Product)).all()
        for p in products:
            history = session.scalars(
                select(PriceHistory)
                .where(PriceHistory.product_id == p.id)
                .order_by(PriceHistory.collected_at.asc())
            ).all()
            for h in history:
                rows.append(
                    {
                        "product_id": p.id,
                        "marketplace": p.marketplace,
                        "marketplace_label": MARKETPLACE_LABELS.get(
                            p.marketplace, p.marketplace
                        ),
                        "title": p.title,
                        "normalized_title": p.normalized_title,
                        "store_name": p.store_name,
                        "trust_score": p.trust_score or 0,
                        "url": p.url,
                        "current_price": h.current_price,
                        "discount_percent": h.discount_percent,
                        "collected_at": h.collected_at,
                    }
                )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["collected_at"] = pd.to_datetime(df["collected_at"])
    return df


@st.cache_data(ttl=120)
def load_alerts() -> pd.DataFrame:
    init_db()
    with get_session() as session:
        alerts = session.scalars(
            select(AlertSent).order_by(AlertSent.sent_at.desc()).limit(50)
        ).all()
        rows = []
        for a in alerts:
            product = session.get(Product, a.product_id)
            if product:
                rows.append(
                    {
                        "alert_type": a.alert_type,
                        "title": product.title,
                        "marketplace": MARKETPLACE_LABELS.get(
                            product.marketplace, product.marketplace
                        ),
                        "sent_at": a.sent_at,
                    }
                )
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def main() -> None:
    config = load_app_config()
    st.title("🎮 Monitor de Preços — Nintendo Switch 2")
    st.caption(f"Produto monitorado: **{config.product.main_term}**")

    df = load_price_data()
    if df.empty:
        st.warning(
            "Nenhum dado coletado ainda. Execute `python -m app.cli run-once` ou `python main.py`."
        )
        return

    st.sidebar.header("Filtros")
    marketplaces = sorted(df["marketplace_label"].unique())
    selected_mp = st.sidebar.multiselect(
        "Marketplaces",
        marketplaces,
        default=marketplaces,
    )
    days = st.sidebar.slider("Período (dias)", 1, 90, 30)
    min_trust = st.sidebar.slider("Confiabilidade mínima", 0, 100, 30)

    cutoff = datetime.utcnow() - timedelta(days=days)
    filtered = df[
        (df["marketplace_label"].isin(selected_mp))
        & (df["collected_at"] >= cutoff)
        & (df["trust_score"] >= min_trust)
    ]

    if filtered.empty:
        st.info("Nenhum registro com os filtros selecionados.")
        return

    latest = (
        filtered.sort_values("collected_at")
        .groupby(["product_id", "marketplace_label"])
        .last()
        .reset_index()
    )
    global_min = latest["current_price"].min()
    global_avg = filtered["current_price"].mean()
    last_collect = filtered["collected_at"].max()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Menor preço consolidado", f"R$ {global_min:,.2f}")
    col2.metric("Média histórica", f"R$ {global_avg:,.2f}")
    col3.metric("Produtos rastreados", len(latest))
    col4.metric("Última coleta", last_collect.strftime("%d/%m %H:%M"))

    st.subheader("Evolução de preços por marketplace")
    agg = (
        filtered.groupby(["collected_at", "marketplace_label"])["current_price"]
        .min()
        .reset_index()
    )
    fig_line = px.line(
        agg,
        x="collected_at",
        y="current_price",
        color="marketplace_label",
        labels={"current_price": "Preço (R$)", "collected_at": "Data"},
    )
    fig_line.update_layout(hovermode="x unified")
    st.plotly_chart(fig_line, use_container_width=True)

    st.subheader("Comparação atual entre marketplaces")
    mp_min = (
        latest.groupby("marketplace_label")["current_price"]
        .min()
        .reset_index()
    )
    fig_bar = px.bar(
        mp_min,
        x="marketplace_label",
        y="current_price",
        labels={"current_price": "Menor preço (R$)"},
        color="marketplace_label",
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Ranking de lojas (menor preço)")
        store_rank = (
            latest.dropna(subset=["store_name"])
            .groupby("store_name")["current_price"]
            .min()
            .sort_values()
            .head(10)
            .reset_index()
        )
        st.dataframe(store_rank, use_container_width=True, hide_index=True)

    with col_b:
        st.subheader("Promoções recentes (alertas)")
        alerts_df = load_alerts()
        if not alerts_df.empty:
            st.dataframe(alerts_df, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum alerta enviado ainda.")

    st.subheader("Tabela de produtos")
    display = latest[
        [
            "title",
            "marketplace_label",
            "store_name",
            "current_price",
            "trust_score",
            "url",
            "collected_at",
        ]
    ].rename(
        columns={
            "title": "Produto",
            "marketplace_label": "Marketplace",
            "store_name": "Loja",
            "current_price": "Preço",
            "trust_score": "Confiança",
            "url": "Link",
            "collected_at": "Coletado em",
        }
    )
    display["Preço"] = display["Preço"].map(lambda x: f"R$ {x:,.2f}")
    st.dataframe(display, use_container_width=True, hide_index=True)

    st.subheader("Exportação")
    ec1, ec2 = st.columns(2)
    if ec1.button("Exportar CSV"):
        path = export_csv()
        st.success(f"Exportado: {path}")
    if ec2.button("Exportar Excel"):
        path = export_excel()
        st.success(f"Exportado: {path}")


if __name__ == "__main__":
    main()
