from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from app.config.settings import PROJECT_ROOT
from app.database.session import get_session, init_db
from app.models.orm import PriceHistory, Product

EXPORTS_DIR = PROJECT_ROOT / "exports"


def _fetch_dataframe() -> pd.DataFrame:
    init_db()
    rows: list[dict] = []
    with get_session() as session:
        products = session.scalars(select(Product)).all()
        for product in products:
            history = session.scalars(
                select(PriceHistory)
                .where(PriceHistory.product_id == product.id)
                .order_by(PriceHistory.collected_at.desc())
            ).all()
            for h in history:
                rows.append(
                    {
                        "product_id": product.id,
                        "marketplace": product.marketplace,
                        "title": product.title,
                        "normalized_title": product.normalized_title,
                        "store_name": product.store_name,
                        "rating": product.rating,
                        "sold_count": product.sold_count,
                        "trust_score": product.trust_score,
                        "url": product.url,
                        "current_price": h.current_price,
                        "original_price": h.original_price,
                        "shipping_price": h.shipping_price,
                        "discount_percent": h.discount_percent,
                        "collected_at": h.collected_at,
                    }
                )
    return pd.DataFrame(rows)


def export_csv(filename: str | None = None) -> Path:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    df = _fetch_dataframe()
    name = filename or f"prices_{datetime.utcnow():%Y%m%d_%H%M%S}.csv"
    path = EXPORTS_DIR / name
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def export_excel(filename: str | None = None) -> Path:
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    df = _fetch_dataframe()
    name = filename or f"prices_{datetime.utcnow():%Y%m%d_%H%M%S}.xlsx"
    path = EXPORTS_DIR / name
    df.to_excel(path, index=False, engine="openpyxl")
    return path
