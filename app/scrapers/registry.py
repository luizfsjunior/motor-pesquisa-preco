from app.config.loader import AppConfig
from app.scrapers.amazon import AmazonScraper
from app.scrapers.base import BaseScraper
from app.scrapers.google_shopping import GoogleShoppingScraper
from app.scrapers.kabum import KabumScraper
from app.scrapers.mercadolivre import MercadoLivreScraper
from app.scrapers.shopee import ShopeeScraper
from app.utils.playwright import PlaywrightManager

SCRAPER_CLASSES: dict[str, type[BaseScraper]] = {
    "shopee": ShopeeScraper,
    "mercadolivre": MercadoLivreScraper,
    "google_shopping": GoogleShoppingScraper,
    "amazon": AmazonScraper,
    "kabum": KabumScraper,
}


def create_scrapers(config: AppConfig, pw: PlaywrightManager | None = None) -> dict[str, BaseScraper]:
    shared_pw = pw or PlaywrightManager()
    shopee_pw = PlaywrightManager(for_shopee=True)
    scrapers: dict[str, BaseScraper] = {}
    for key in config.marketplaces.enabled_keys():
        cls = SCRAPER_CLASSES.get(key)
        if cls:
            browser = shopee_pw if key == "shopee" else shared_pw
            scrapers[key] = cls(config, browser)
    return scrapers
