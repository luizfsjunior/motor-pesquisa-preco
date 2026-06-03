import time

from loguru import logger

from app.alerts.telegram import get_alert_sender
from app.config.loader import AppConfig, load_app_config
from app.database.repository import ProductRepository
from app.database.session import get_session, init_db
from app.normalization.title import normalize_title, should_ignore_title
from app.scrapers.registry import create_scrapers
from app.services.promotion import PromotionService
from app.services.trust_score import calculate_trust_score
from app.utils.playwright import PlaywrightManager


class PriceMonitorService:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_app_config()
        self.alert_sender = get_alert_sender()

    async def run_cycle(self) -> dict[str, int]:
        init_db()
        stats = {"scraped": 0, "saved": 0, "alerts": 0, "rejected": 0}
        pw = PlaywrightManager()
        scrapers = create_scrapers(self.config, pw)
        start = time.perf_counter()

        try:
            for term in self.config.product.search_terms:
                for marketplace, scraper in scrapers.items():
                    try:
                        logger.bind(category="scraping").info(
                            "Scraping {} for '{}'", marketplace, term
                        )
                        products = await scraper.search_products(term)
                        stats["scraped"] += len(products)
                        with get_session() as session:
                            repo = ProductRepository(session)
                            promo_svc = PromotionService(repo, self.config)
                            for scraped in products:
                                if scraped.is_sponsored:
                                    continue
                                if should_ignore_title(
                                    scraped.title, self.config.product.ignored_terms
                                ):
                                    stats["rejected"] += 1
                                    continue
                                trust = calculate_trust_score(scraped, self.config)
                                if trust.rejected:
                                    stats["rejected"] += 1
                                    logger.debug(
                                        "Rejected {}: {}",
                                        scraped.title[:50],
                                        trust.reasons,
                                    )
                                    continue
                                normalized = normalize_title(
                                    scraped.title, self.config.product
                                )
                                db_product, is_new = repo.upsert_product(
                                    scraped, normalized, trust.score
                                )
                                promotions = promo_svc.detect_promotions(
                                    db_product, scraped, trust, is_new
                                )
                                repo.add_price_snapshot(db_product, scraped)
                                stats["saved"] += 1
                                for promo in promotions:
                                    if repo.alert_already_sent(
                                        db_product.id, promo.alert_type
                                    ):
                                        continue
                                    if self.alert_sender.send_promotion(promo):
                                        repo.record_alert(
                                            db_product.id, promo.alert_type
                                        )
                                        stats["alerts"] += 1
                    except Exception as exc:
                        logger.error(
                            "Error scraping {} for '{}': {}",
                            marketplace,
                            term,
                            exc,
                        )
        finally:
            for scraper in scrapers.values():
                await scraper.close()

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        logger.bind(category="performance").info(
            "Cycle completed in {}ms — scraped={}, saved={}, alerts={}, rejected={}",
            elapsed_ms,
            stats["scraped"],
            stats["saved"],
            stats["alerts"],
            stats["rejected"],
        )
        return stats
