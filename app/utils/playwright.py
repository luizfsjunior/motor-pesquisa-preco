import asyncio
import random
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.config.settings import get_settings

USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    ),
]


class PlaywrightManager:
    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def start(self) -> BrowserContext:
        if self._context is not None:
            return self._context
        settings = get_settings()
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=settings.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = await self._browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": 1366, "height": 768},
        )
        return self._context

    async def new_page(self) -> Page:
        context = await self.start()
        page = await context.new_page()
        page.set_default_timeout(30000)
        return page

    async def close(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


async def auto_scroll(page: Page, pause_ms: int = 800, max_scrolls: int = 5) -> None:
    for _ in range(max_scrolls):
        await page.evaluate("window.scrollBy(0, window.innerHeight)")
        await asyncio.sleep(pause_ms / 1000 + random.uniform(0.1, 0.4))


def parse_brl_price(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = (
        text.replace("R$", "")
        .replace("\xa0", "")
        .replace(".", "")
        .replace(",", ".")
        .strip()
    )
    digits = "".join(c for c in cleaned if c.isdigit() or c == ".")
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def parse_int_from_text(text: str | None) -> int | None:
    if not text:
        return None
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else None
