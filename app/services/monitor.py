import time

from loguru import logger

from app.alerts.telegram import get_alert_sender
from app.config.loader import AppConfig, load_app_config
from app.config.settings import get_settings
from app.database.repository import ProductRepository
from app.database.session import get_session, init_db
from app.normalization.relevance import is_relevant_product
from app.normalization.title import normalize_title, should_ignore_title
from app.scrapers.registry import create_scrapers
from app.services.cycle_report import CycleTracker, log_cycle_summary
from app.services.promotion import PromotionService
from app.services.trust_score import calculate_trust_score
from app.utils.playwright import PlaywrightManager


class PriceMonitorService:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_app_config()
        self.alert_sender = get_alert_sender()

    async def run_cycle(self) -> dict[str, int]:
        init_db()
        stats: dict[str, int] = {
            "scraped": 0,
            "saved": 0,
            "alerts": 0,
            "rejected": 0,
            "digest_sent": 0,
        }
        settings = get_settings()
        if settings.telegram_enabled:
            logger.info("Telegram: enabled (token and chat_id present)")
        else:
            logger.warning(
                "Telegram: DISABLED — defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nos secrets ou .env"
            )
        max_fallback = self.config.alerts.effective_fallback_max_price(self.config.product)
        logger.info(
            "Fallback menor preço: ofertas com preço total < R$ {:.0f}",
            max_fallback,
        )
        tracker = CycleTracker(fallback_max_price=max_fallback)
        pw = PlaywrightManager()
        scrapers = create_scrapers(self.config, pw)
        start = time.perf_counter()

        try:
            for term in self.config.product.search_terms:
                for marketplace, scraper in scrapers.items():
                    batch_saved = 0
                    batch_rejected = 0
                    try:
                        logger.bind(category="scraping").info(
                            "Scrape start | marketplace={} | term='{}'",
                            marketplace,
                            term,
                        )
                        products = await scraper.search_products(term)
                        stats["scraped"] += len(products)
                        with get_session() as session:
                            repo = ProductRepository(session)
                            promo_svc = PromotionService(repo, self.config)
                            for scraped in products:
                                if scraped.is_sponsored:
                                    continue
                                tracker.consider_raw(scraped)
                                if should_ignore_title(
                                    scraped.title, self.config.product.ignored_terms
                                ):
                                    stats["rejected"] += 1
                                    batch_rejected += 1
                                    continue
                                rel_price = (
                                    None
                                    if scraped.price_unknown
                                    else scraped.total_price
                                )
                                if not is_relevant_product(
                                    scraped.title,
                                    self.config.product.relevance,
                                    price=rel_price,
                                ):
                                    stats["rejected"] += 1
                                    batch_rejected += 1
                                    logger.debug(
                                        "Irrelevant listing | title={}",
                                        scraped.title[:70],
                                    )
                                    continue
                                trust = calculate_trust_score(scraped, self.config)
                                tracker.consider_seen(scraped, trust.score)
                                if trust.rejected:
                                    stats["rejected"] += 1
                                    batch_rejected += 1
                                    logger.debug(
                                        "Rejected | title={} | reasons={}",
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
                                if not scraped.price_unknown:
                                    repo.add_price_snapshot(db_product, scraped)
                                stats["saved"] += 1
                                batch_saved += 1
                                if scraped.price_unknown or scraped.current_price <= 0:
                                    tracker.consider_discovery(scraped, trust.score)
                                else:
                                    tracker.consider_saved(scraped, trust.score)
                                if not scraped.price_unknown:
                                    promotions = promo_svc.detect_promotions(
                                        db_product, scraped, trust, is_new
                                    )
                                else:
                                    promotions = []
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
                        tracker.record_attempt(
                            marketplace, term, len(products), batch_saved, batch_rejected
                        )
                        logger.bind(category="scraping").info(
                            "Scrape done | marketplace={} | term='{}' | raw={} saved={} rejected={}",
                            marketplace,
                            term,
                            len(products),
                            batch_saved,
                            batch_rejected,
                        )
                    except Exception as exc:
                        tracker.record_error(marketplace, term, exc)
        finally:
            for scraper in scrapers.values():
                await scraper.close()

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        digest = tracker.build_digest(
            main_term=self.config.product.main_term,
            scraped=stats["scraped"],
            saved=stats["saved"],
            rejected=stats["rejected"],
            alerts=stats["alerts"],
            elapsed_ms=elapsed_ms,
        )
        digest_sent = self._send_fallback_if_needed(digest, stats["alerts"])
        stats["digest_sent"] = int(digest_sent)
        if not settings.telegram_enabled:
            logger.warning("Telegram digest skipped — credenciais ausentes")
        elif not digest_sent:
            logger.warning("Telegram digest not sent — verifique logs acima")
        log_cycle_summary(
            digest,
            telegram_enabled=settings.telegram_enabled,
            digest_sent=digest_sent,
        )
        return stats

    def _send_fallback_if_needed(self, digest, alerts: int) -> bool:
        if alerts > 0:
            logger.info(
                "Skipping cycle digest — {} promotion alert(s) already sent", alerts
            )
            return False
        if digest.scraped == 0:
            sent = self.alert_sender.send_cycle_no_data(digest)
            logger.info("Telegram cycle_no_data sent={}", sent)
            return sent
        if digest.lowest:
            sent = self.alert_sender.send_cycle_digest(digest)
            logger.info("Telegram cycle_digest sent={}", sent)
            return sent
        sent = self.alert_sender.send_cycle_all_filtered(digest)
        logger.info("Telegram cycle_all_filtered sent={}", sent)
        return sent
