from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import AlertSent, PriceHistory, Product
from app.models.schemas import ScrapedProduct


class ProductRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_external(self, marketplace: str, external_id: str) -> Product | None:
        stmt = select(Product).where(
            Product.marketplace == marketplace,
            Product.external_id == external_id,
        )
        return self.session.scalars(stmt).first()

    def upsert_product(
        self,
        scraped: ScrapedProduct,
        normalized_title: str,
        trust_score: int,
    ) -> tuple[Product, bool]:
        existing = self.get_by_external(scraped.marketplace, scraped.external_id)
        is_new = existing is None
        if existing:
            existing.title = scraped.title
            existing.normalized_title = normalized_title
            existing.url = scraped.url
            existing.image_url = scraped.image_url
            existing.store_name = scraped.store_name
            existing.rating = scraped.rating
            existing.sold_count = scraped.sold_count
            existing.trust_score = trust_score
            existing.updated_at = datetime.utcnow()
            product = existing
        else:
            product = Product(
                marketplace=scraped.marketplace,
                external_id=scraped.external_id,
                title=scraped.title,
                normalized_title=normalized_title,
                url=scraped.url,
                image_url=scraped.image_url,
                store_name=scraped.store_name,
                rating=scraped.rating,
                sold_count=scraped.sold_count,
                trust_score=trust_score,
            )
            self.session.add(product)
            self.session.flush()
        return product, is_new

    def add_price_snapshot(
        self,
        product: Product,
        scraped: ScrapedProduct,
    ) -> PriceHistory:
        history = PriceHistory(
            product_id=product.id,
            current_price=scraped.total_price,
            original_price=scraped.original_price,
            shipping_price=scraped.shipping_price,
            discount_percent=scraped.discount_percent,
            collected_at=scraped.collected_at,
        )
        self.session.add(history)
        return history

    def get_price_history(
        self,
        product_id: int,
        days: int | None = None,
    ) -> list[PriceHistory]:
        stmt = select(PriceHistory).where(PriceHistory.product_id == product_id)
        if days:
            since = datetime.utcnow() - timedelta(days=days)
            stmt = stmt.where(PriceHistory.collected_at >= since)
        stmt = stmt.order_by(PriceHistory.collected_at.asc())
        return list(self.session.scalars(stmt).all())

    def get_historical_min(self, product_id: int) -> float | None:
        stmt = select(func.min(PriceHistory.current_price)).where(
            PriceHistory.product_id == product_id
        )
        return self.session.scalar(stmt)

    def get_historical_average(
        self,
        product_id: int,
        days: int = 30,
    ) -> float | None:
        since = datetime.utcnow() - timedelta(days=days)
        stmt = select(func.avg(PriceHistory.current_price)).where(
            PriceHistory.product_id == product_id,
            PriceHistory.collected_at >= since,
        )
        return self.session.scalar(stmt)

    def get_consolidated_percentile_20(self) -> float | None:
        stmt = select(func.min(PriceHistory.current_price)).select_from(PriceHistory)
        subq = (
            select(PriceHistory.current_price)
            .order_by(PriceHistory.current_price.asc())
            .limit(100)
        )
        prices = list(self.session.scalars(subq).all())
        if len(prices) < 5:
            return self.session.scalar(select(func.avg(PriceHistory.current_price)))
        idx = max(0, int(len(prices) * 0.2) - 1)
        return float(prices[idx])

    def alert_already_sent(self, product_id: int, alert_type: str) -> bool:
        stmt = select(AlertSent).where(
            AlertSent.product_id == product_id,
            AlertSent.alert_type == alert_type,
        )
        return self.session.scalars(stmt).first() is not None

    def record_alert(self, product_id: int, alert_type: str) -> AlertSent:
        alert = AlertSent(product_id=product_id, alert_type=alert_type)
        self.session.add(alert)
        return alert

    def get_all_products_with_latest_price(self) -> list[dict]:
        products = list(self.session.scalars(select(Product)).all())
        result = []
        for p in products:
            latest = self.session.scalars(
                select(PriceHistory)
                .where(PriceHistory.product_id == p.id)
                .order_by(PriceHistory.collected_at.desc())
                .limit(1)
            ).first()
            if latest:
                result.append({"product": p, "latest": latest})
        return result

    def get_recent_alerts(self, limit: int = 20) -> list[AlertSent]:
        stmt = (
            select(AlertSent)
            .order_by(AlertSent.sent_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())
