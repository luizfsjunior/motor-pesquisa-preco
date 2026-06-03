from datetime import datetime, timedelta

from app.config.loader import AppConfig
from app.database.repository import ProductRepository
from app.models.orm import Product
from app.models.schemas import PromotionAlert, ScrapedProduct, TrustResult


class PromotionService:
    def __init__(self, repo: ProductRepository, config: AppConfig) -> None:
        self.repo = repo
        self.config = config

    def detect_promotions(
        self,
        product: Product,
        scraped: ScrapedProduct,
        trust: TrustResult,
        is_new_product: bool,
    ) -> list[PromotionAlert]:
        if trust.score < self.config.trust.minimum_score_to_alert:
            return []

        alerts: list[PromotionAlert] = []
        current = scraped.total_price
        history = self.repo.get_price_history(product.id)
        past_prices = [h.current_price for h in history if h.collected_at < scraped.collected_at]

        hist_min = min(past_prices) if past_prices else None
        avg = self.repo.get_historical_average(
            product.id, self.config.promotion.history_days_for_average
        )
        if avg is None and past_prices:
            avg = sum(past_prices) / len(past_prices)

        discount_vs_avg = None
        if avg and avg > 0:
            discount_vs_avg = round((1 - current / avg) * 100, 1)

        if (
            self.config.alerts.notify_new_lowest_price
            and hist_min is not None
            and current < hist_min
        ):
            alerts.append(
                self._build_alert(
                    "new_lowest_price",
                    product,
                    scraped,
                    trust,
                    discount_vs_avg,
                    avg,
                    "Novo menor preço histórico!",
                )
            )
        elif (
            discount_vs_avg is not None
            and discount_vs_avg >= self.config.alerts.minimum_discount_percent
        ):
            alerts.append(
                self._build_alert(
                    "discount_vs_average",
                    product,
                    scraped,
                    trust,
                    discount_vs_avg,
                    avg,
                    f"Desconto de {discount_vs_avg}% vs média histórica",
                )
            )

        if self._detect_abnormal_drop(product.id, current):
            alerts.append(
                self._build_alert(
                    "abnormal_drop",
                    product,
                    scraped,
                    trust,
                    discount_vs_avg,
                    avg,
                    "Queda abrupta de preço nas últimas 24h",
                )
            )

        if self.config.alerts.notify_new_products and is_new_product:
            percentile = self.repo.get_consolidated_percentile_20()
            if percentile and current < percentile:
                alerts.append(
                    self._build_alert(
                        "new_cheap_listing",
                        product,
                        scraped,
                        trust,
                        discount_vs_avg,
                        avg,
                        "Novo anúncio com preço abaixo do mercado",
                    )
                )

        return alerts

    def _detect_abnormal_drop(self, product_id: int, current: float) -> bool:
        history = self.repo.get_price_history(product_id, days=2)
        if len(history) < 2:
            return False
        since = datetime.utcnow() - timedelta(hours=24)
        recent = [h for h in history if h.collected_at >= since]
        if len(recent) < 2:
            return False
        previous = recent[-2].current_price
        if previous <= 0:
            return False
        drop = (1 - current / previous) * 100
        return drop >= self.config.promotion.abnormal_drop_percent

    def _build_alert(
        self,
        alert_type: str,
        product: Product,
        scraped: ScrapedProduct,
        trust: TrustResult,
        discount: float | None,
        average: float | None,
        extra: str,
    ) -> PromotionAlert:
        return PromotionAlert(
            alert_type=alert_type,
            product_id=product.id,
            title=product.title,
            marketplace=product.marketplace,
            current_price=scraped.total_price,
            discount_percent=discount or scraped.discount_percent,
            historical_average=average,
            store_name=scraped.store_name,
            url=scraped.url,
            trust_score=trust.score,
            trust_level=trust.level,
            message_extra=extra,
        )
