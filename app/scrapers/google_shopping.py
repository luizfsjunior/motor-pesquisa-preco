import re
import urllib.parse
from datetime import datetime

from loguru import logger

from app.models.schemas import ScrapedProduct
from app.scrapers.base import BaseScraper
from app.utils.playwright import auto_scroll, parse_brl_price
from app.utils.retry import async_retry


class GoogleShoppingScraper(BaseScraper):
    marketplace = "google_shopping"

    @async_retry(max_attempts=2, delay_seconds=3.0)
    async def search_products(self, query: str) -> list[ScrapedProduct]:
        encoded = urllib.parse.quote(query)
        url = (
            f"https://www.google.com.br/search?q={encoded}"
            "&tbm=shop&hl=pt-BR&gl=br"
        )
        page = await self._pw.new_page()
        products: list[ScrapedProduct] = []
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            content = await page.content()
            if "captcha" in content.lower() or "unusual traffic" in content.lower():
                logger.warning(
                    "Google Shopping CAPTCHA/block detected for '{}'", query
                )
                return []
            await auto_scroll(
                page,
                pause_ms=self.config.scraping.scroll_pause_ms,
                max_scrolls=3,
            )
            cards = await page.query_selector_all(
                "div[data-docid], li[data-oid], div.sh-dgr__grid-result"
            )
            if not cards:
                cards = await page.query_selector_all("div.sh-dgr__content")
            idx = 0
            for card in cards[:30]:
                title_el = await card.query_selector(
                    "h3, h4, .tAxDx, .Xjkr3b"
                )
                price_el = await card.query_selector(
                    "span[class*='price'], .a8Pemb, .g9W7bc"
                )
                link_el = await card.query_selector("a[href]")
                merchant_el = await card.query_selector(
                    ".IuHnof, .E5ocAb, span[class*='merchant']"
                )
                img_el = await card.query_selector("img")
                title = (await title_el.inner_text()).strip() if title_el else ""
                price_text = await price_el.inner_text() if price_el else ""
                price = parse_brl_price(price_text)
                href = await link_el.get_attribute("href") if link_el else None
                if not title or not price:
                    continue
                if "R$" not in price_text and price_text:
                    continue
                store = await merchant_el.inner_text() if merchant_el else "Desconhecida"
                if self.config.filters.only_national_results and href:
                    if not any(
                        t in href.lower()
                        for t in [".com.br", ".br/", "mercadolivre", "shopee", "magazineluiza", "kabum", "amazon.com.br"]
                    ):
                        if href.startswith("http") and ".br" not in href:
                            continue
                image_url = await img_el.get_attribute("src") if img_el else None
                if href and href.startswith("/url?"):
                    match = re.search(r"q=([^&]+)", href)
                    if match:
                        href = urllib.parse.unquote(match.group(1))
                external_id = f"gs_{idx}_{hash(title) % 10**8}"
                idx += 1
                products.append(
                    ScrapedProduct(
                        marketplace=self.marketplace,
                        external_id=external_id,
                        title=title,
                        current_price=price,
                        store_name=store.strip() if store else None,
                        url=href or url,
                        image_url=image_url,
                        collected_at=datetime.utcnow(),
                    )
                )
        except Exception as exc:
            logger.warning("Google Shopping degraded mode: {}", exc)
        finally:
            await page.close()
        logger.bind(category="scraping").info(
            "Google Shopping returned {} items for '{}'", len(products), query
        )
        return products
