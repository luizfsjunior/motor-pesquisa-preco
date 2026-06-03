from abc import ABC, abstractmethod

from app.config.loader import AppConfig
from app.models.schemas import ScrapedProduct
from app.utils.playwright import PlaywrightManager


class BaseScraper(ABC):
    marketplace: str

    def __init__(self, config: AppConfig, pw: PlaywrightManager | None = None) -> None:
        self.config = config
        self._pw = pw or PlaywrightManager()

    @abstractmethod
    async def search_products(self, query: str) -> list[ScrapedProduct]:
        pass

    async def close(self) -> None:
        await self._pw.close()
