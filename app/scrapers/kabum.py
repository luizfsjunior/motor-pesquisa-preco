from loguru import logger

from app.models.schemas import ScrapedProduct
from app.scrapers.base import BaseScraper


class KabumScraper(BaseScraper):
    marketplace = "kabum"

    async def search_products(self, query: str) -> list[ScrapedProduct]:
        logger.info("Kabum scraper disabled — enable in config/products.yaml")
        return []
