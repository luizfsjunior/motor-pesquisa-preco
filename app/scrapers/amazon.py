from loguru import logger

from app.models.schemas import ScrapedProduct
from app.scrapers.base import BaseScraper


class AmazonScraper(BaseScraper):
    marketplace = "amazon"

    async def search_products(self, query: str) -> list[ScrapedProduct]:
        logger.info("Amazon scraper disabled — enable in config/products.yaml")
        return []
