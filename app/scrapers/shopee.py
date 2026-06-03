import re
import urllib.parse
from datetime import datetime

from loguru import logger

from app.models.schemas import ScrapedProduct
from app.scrapers.base import BaseScraper
from app.utils.playwright import auto_scroll, parse_brl_price, parse_int_from_text
from app.utils.retry import async_retry


class ShopeeScraper(BaseScraper):
    marketplace = "shopee"

    @async_retry(max_attempts=3, delay_seconds=2.0)
    async def search_products(self, query: str) -> list[ScrapedProduct]:
        api_results = await self._search_via_api(query)
        if api_results:
            logger.bind(category="scraping").info(
                "Shopee API returned {} items for '{}'", len(api_results), query
            )
            return api_results
        return await self._search_via_playwright(query)

    async def _search_via_api(self, query: str) -> list[ScrapedProduct]:
        encoded = urllib.parse.quote(query)
        url = (
            "https://shopee.com.br/api/v4/search/search_items"
            f"?keyword={encoded}&limit=50&newest=0&order=desc&page_type=search"
            "&scenario=PAGE_GLOBAL_SEARCH"
        )
        page = await self._pw.new_page()
        try:
            await page.goto("https://shopee.com.br/", wait_until="domcontentloaded")
            response = await page.request.get(
                url,
                headers={
                    "Accept": "application/json",
                    "Referer": f"https://shopee.com.br/search?keyword={encoded}",
                },
            )
            if response.status != 200:
                return []
            data = await response.json()
            items = data.get("items") or []
            products: list[ScrapedProduct] = []
            for entry in items:
                item_basic = entry.get("item_basic") or entry
                parsed = self._parse_api_item(item_basic)
                if parsed:
                    products.append(parsed)
            return products
        except Exception as exc:
            logger.warning("Shopee API failed, fallback to Playwright: {}", exc)
            return []
        finally:
            await page.close()

    def _parse_api_item(self, item: dict) -> ScrapedProduct | None:
        item_id = item.get("itemid") or item.get("item_id")
        shop_id = item.get("shopid") or item.get("shop_id")
        if not item_id or not shop_id:
            return None
        title = item.get("name") or ""
        if not title:
            return None
        price_raw = item.get("price") or item.get("price_min") or 0
        price = float(price_raw) / 100000 if price_raw > 10000 else float(price_raw)
        original_raw = item.get("price_before_discount") or item.get("price_max")
        original = None
        if original_raw:
            original = (
                float(original_raw) / 100000
                if original_raw > 10000
                else float(original_raw)
            )
        discount = None
        if original and original > price:
            discount = round((1 - price / original) * 100, 1)
        image = item.get("image")
        image_url = f"https://cf.shopee.com.br/file/{image}" if image else None
        sold = item.get("historical_sold") or item.get("sold")
        rating = item.get("item_rating", {}).get("rating_star")
        shop_name = item.get("shop_name") or item.get("shop_location")
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")[:80]
        product_url = (
            f"https://shopee.com.br/{slug}-i.{shop_id}.{item_id}"
        )
        return ScrapedProduct(
            marketplace=self.marketplace,
            external_id=f"{shop_id}_{item_id}",
            title=title,
            current_price=price,
            original_price=original,
            discount_percent=discount,
            store_name=shop_name,
            rating=float(rating) if rating else None,
            sold_count=int(sold) if sold else None,
            url=product_url,
            image_url=image_url,
            collected_at=datetime.utcnow(),
        )

    async def _search_via_playwright(self, query: str) -> list[ScrapedProduct]:
        encoded = urllib.parse.quote(query)
        url = f"https://shopee.com.br/search?keyword={encoded}"
        page = await self._pw.new_page()
        products: list[ScrapedProduct] = []
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await auto_scroll(
                page,
                pause_ms=self.config.scraping.scroll_pause_ms,
                max_scrolls=4,
            )
            cards = await page.query_selector_all(
                "div[class*='shopee-search-item-result'] a, li.shopee-search-item-result__item a"
            )
            seen: set[str] = set()
            for card in cards[:40]:
                href = await card.get_attribute("href")
                if not href or href in seen:
                    continue
                seen.add(href)
                full_url = href if href.startswith("http") else f"https://shopee.com.br{href}"
                ext_match = re.search(r"\.(\d+)\.(\d+)", href)
                external_id = (
                    f"{ext_match.group(1)}_{ext_match.group(2)}"
                    if ext_match
                    else href
                )
                parent = await card.evaluate_handle(
                    "el => el.closest('li') || el.parentElement"
                )
                parent_el = parent.as_element()
                if not parent_el:
                    continue
                title_el = await parent_el.query_selector(
                    "div[class*='title'], .ie3A\\+n"
                )
                price_el = await parent_el.query_selector(
                    "span[class*='price'], .ZEgDH9"
                )
                title = (await title_el.inner_text()) if title_el else ""
                price_text = (await price_el.inner_text()) if price_el else ""
                price = parse_brl_price(price_text)
                if not title or not price:
                    continue
                products.append(
                    ScrapedProduct(
                        marketplace=self.marketplace,
                        external_id=external_id,
                        title=title.strip(),
                        current_price=price,
                        url=full_url,
                        collected_at=datetime.utcnow(),
                    )
                )
        finally:
            await page.close()
        logger.bind(category="scraping").info(
            "Shopee Playwright returned {} items for '{}'", len(products), query
        )
        return products
