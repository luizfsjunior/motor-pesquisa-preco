from collections import defaultdict
from dataclasses import dataclass, field

from loguru import logger

from app.models.schemas import CycleDigest, CycleLowestOffer, ScrapedProduct


@dataclass
class ScrapeAttempt:
    marketplace: str
    term: str
    raw_count: int = 0
    saved: int = 0
    rejected: int = 0
    error: str | None = None


@dataclass
class CycleTracker:
    fallback_max_price: float
    attempts: list[ScrapeAttempt] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    lowest_saved: CycleLowestOffer | None = None
    lowest_seen: CycleLowestOffer | None = None
    lowest_below_cap: CycleLowestOffer | None = None
    candidates_below_cap: int = 0

    def record_attempt(
        self,
        marketplace: str,
        term: str,
        raw_count: int,
        saved: int,
        rejected: int,
    ) -> None:
        self.attempts.append(
            ScrapeAttempt(
                marketplace=marketplace,
                term=term,
                raw_count=raw_count,
                saved=saved,
                rejected=rejected,
            )
        )
        if raw_count == 0:
            logger.bind(category="scraping").warning(
                "Scraper returned 0 items | marketplace={} | term='{}'",
                marketplace,
                term,
            )

    def record_error(self, marketplace: str, term: str, exc: Exception) -> None:
        msg = f"{marketplace} + '{term}': {exc}"
        self.errors.append(msg)
        self.attempts.append(
            ScrapeAttempt(
                marketplace=marketplace,
                term=term,
                raw_count=0,
                saved=0,
                rejected=0,
                error=str(exc),
            )
        )
        logger.error("Scrape failed | marketplace={} | term='{}' | error={}", marketplace, term, exc)

    def consider_raw(self, scraped: ScrapedProduct) -> None:
        """Qualquer item do scrape abaixo do teto (ignora filtros/trust)."""
        if scraped.is_sponsored:
            return
        if scraped.total_price >= self.fallback_max_price:
            return
        self.candidates_below_cap += 1
        offer = _offer_from_scraped(
            scraped,
            trust_score=0,
            passed_filters=False,
            below_price_cap=True,
        )
        if (
            self.lowest_below_cap is None
            or offer.total_price < self.lowest_below_cap.total_price
        ):
            self.lowest_below_cap = offer

    def consider_seen(self, scraped: ScrapedProduct, trust_score: int) -> None:
        offer = _offer_from_scraped(scraped, trust_score, passed_filters=False)
        if self.lowest_seen is None or offer.total_price < self.lowest_seen.total_price:
            self.lowest_seen = offer

    def consider_saved(self, scraped: ScrapedProduct, trust_score: int) -> None:
        offer = _offer_from_scraped(scraped, trust_score, passed_filters=True)
        if self.lowest_saved is None or offer.total_price < self.lowest_saved.total_price:
            self.lowest_saved = offer
        self.consider_seen(scraped, trust_score)

    def build_digest(
        self,
        main_term: str,
        scraped: int,
        saved: int,
        rejected: int,
        alerts: int,
        elapsed_ms: int,
    ) -> CycleDigest:
        lowest, passed, below_cap = self._pick_lowest_for_digest()
        return CycleDigest(
            main_term=main_term,
            scraped=scraped,
            saved=saved,
            rejected=rejected,
            alerts=alerts,
            elapsed_ms=elapsed_ms,
            fallback_max_price=self.fallback_max_price,
            candidates_below_cap=self.candidates_below_cap,
            lowest=lowest,
            lowest_passed_filters=passed,
            lowest_below_cap=below_cap,
            marketplace_lines=_marketplace_summary_lines(self.attempts),
            errors=list(self.errors),
            attempts_total=len(self.attempts),
            attempts_empty=sum(1 for a in self.attempts if a.raw_count == 0 and not a.error),
            attempts_failed=sum(1 for a in self.attempts if a.error),
        )

    def _pick_lowest_for_digest(
        self,
    ) -> tuple[CycleLowestOffer | None, bool, bool]:
        if self.lowest_saved:
            return self.lowest_saved, True, False
        if self.lowest_below_cap:
            return self.lowest_below_cap, False, True
        if self.lowest_seen:
            return self.lowest_seen, False, False
        return None, False, False


def _offer_from_scraped(
    scraped: ScrapedProduct,
    trust_score: int,
    *,
    passed_filters: bool,
    below_price_cap: bool = False,
) -> CycleLowestOffer:
    return CycleLowestOffer(
        title=scraped.title,
        marketplace=scraped.marketplace,
        total_price=scraped.total_price,
        store_name=scraped.store_name,
        url=scraped.url,
        trust_score=trust_score,
        passed_filters=passed_filters,
        below_price_cap=below_price_cap,
    )


def _marketplace_summary_lines(attempts: list[ScrapeAttempt]) -> list[str]:
    by_mp: dict[str, dict[str, int]] = defaultdict(
        lambda: {"raw": 0, "saved": 0, "empty": 0, "failed": 0}
    )
    for a in attempts:
        entry = by_mp[a.marketplace]
        entry["raw"] += a.raw_count
        entry["saved"] += a.saved
        if a.error:
            entry["failed"] += 1
        elif a.raw_count == 0:
            entry["empty"] += 1
    lines: list[str] = []
    for mp in sorted(by_mp):
        e = by_mp[mp]
        lines.append(
            f"{mp}: raw={e['raw']} saved={e['saved']} "
            f"empty_searches={e['empty']} failed={e['failed']}"
        )
    return lines


def log_cycle_summary(digest: CycleDigest, *, telegram_enabled: bool, digest_sent: bool) -> None:
    lines = [
        "========== CYCLE SUMMARY ==========",
        f"product={digest.main_term}",
        f"elapsed_ms={digest.elapsed_ms}",
        f"scraped={digest.scraped} saved={digest.saved} rejected={digest.rejected} alerts={digest.alerts}",
        f"fallback_max_price={digest.fallback_max_price:.0f} candidates_below_cap={digest.candidates_below_cap}",
        f"searches={digest.attempts_total} empty={digest.attempts_empty} failed={digest.attempts_failed}",
        f"telegram_enabled={telegram_enabled} fallback_digest_sent={digest_sent}",
    ]
    lines.extend(f"  {line}" for line in digest.marketplace_lines)
    if digest.lowest:
        if digest.lowest_passed_filters:
            src = "saved"
        elif digest.lowest_below_cap:
            src = "below_cap"
        else:
            src = "seen_only"
        lines.append(
            f"lowest_price[{src}]={digest.lowest.total_price:.2f} "
            f"marketplace={digest.lowest.marketplace} title={digest.lowest.title[:60]!r}"
        )
    else:
        lines.append("lowest_price=none")
    if digest.errors:
        lines.append(f"errors ({len(digest.errors)}):")
        for err in digest.errors[:10]:
            lines.append(f"  - {err}")
    lines.append("===================================")
    block = "\n".join(lines)
    logger.bind(category="performance").info(block)
    if digest.scraped == 0:
        logger.warning(
            "Cycle collected zero products — check scrapers, selectors, or bot blocking (common on GitHub Actions)"
        )
