import re
import urllib.parse
from datetime import datetime

from loguru import logger

from app.models.schemas import ScrapedProduct
from app.scrapers.base import BaseScraper
from app.utils.playwright import auto_scroll, parse_brl_price, parse_int_from_text
from app.utils.retry import async_retry


class MercadoLivreScraper(BaseScraper):
    marketplace = "mercadolivre"

    @async_retry(max_attempts=3, delay_seconds=2.0)
    async def search_products(self, query: str) -> list[ScrapedProduct]:
        all_products: list[ScrapedProduct] = []
        max_pages = self.config.scraping.max_pages
        for page_num in range(1, max_pages + 1):
            batch = await self._scrape_page(query, page_num)
            all_products.extend(batch)
            if not batch:
                break
        logger.bind(category="scraping").info(
            "Mercado Livre returned {} items for '{}'", len(all_products), query
        )
        return all_products

    async def _scrape_page(self, query: str, page: int) -> list[ScrapedProduct]:
        encoded = urllib.parse.quote(query)
        offset = (page - 1) * 48 + 1
        url = (
            f"https://lista.mercadolivre.com.br/{encoded}"
            f"_Desde_{offset}_NoIndex_True"
        )
        if self.config.filters.only_new_products:
            url += "_ITEM*CONDITION_2230284"
        page_obj = await self._pw.new_page()
        products: list[ScrapedProduct] = []
        try:
            await page_obj.goto(url, wait_until="domcontentloaded", timeout=60000)
            await auto_scroll(
                page_obj,
                pause_ms=self.config.scraping.scroll_pause_ms,
                max_scrolls=3,
            )
            items = await page_obj.query_selector_all(
                "li.ui-search-layout__item, div.ui-search-layout__item"
            )
            for item in items:
                sponsored = await item.query_selector(
                    ".poly-component__ads-promotions, .ui-search-item__group__element--ads"
                )
                if sponsored:
                    continue
                link_el = await item.query_selector("a.ui-search-link, a.poly-component__title")
                if not link_el:
                    continue
                href = await link_el.get_attribute("href")
                title = (await link_el.inner_text()).strip()
                if not href or not title:
                    continue
                if self.config.filters.only_national_results:
                    if ".com.ar" in href or "mercadolibre.com" in href:
                        continue
                price_el = await item.query_selector(
                    ".andes-money-amount__fraction, span.price-tag-fraction"
                )
                price_text = await price_el.inner_text() if price_el else None
                price = parse_brl_price(price_text)
                if not price:
                    continue
                shipping_el = await item.query_selector(
                    ".ui-search-item__shipping, .poly-component__shipping"
                )
                shipping_text = (
                    await shipping_el.inner_text() if shipping_el else None
                )
                shipping = 0.0 if shipping_text and "grátis" in shipping_text.lower() else None
                condition_el = await item.query_selector(
                    ".ui-search-item__subtitle, .poly-component__subtitle"
                )
                condition = await condition_el.inner_text() if condition_el else None
                if self.config.filters.only_new_products and condition:
                    if "usado" in condition.lower():
                        continue
                reviews_el = await item.query_selector(
                    ".ui-search-reviews__rating-number, .poly-reviews__rating"
                )
                rating = None
                if reviews_el:
                    rating_text = await reviews_el.inner_text()
                    try:
                        rating = float(rating_text.replace(",", "."))
                    except ValueError:
                        pass
                sold_el = await item.query_selector(
                    ".ui-search-item__group__element--quantity-sold, .poly-component__quantity"
                )
                sold_count = None
                if sold_el:
                    sold_text = await sold_el.inner_text()
                    sold_count = parse_int_from_text(sold_text)
                img_el = await item.query_selector("img")
                image_url = await img_el.get_attribute("src") if img_el else None
                ext_id_match = re.search(r"MLB-?(\d+)", href)
                external_id = ext_id_match.group(1) if ext_id_match else href
                store_el = await item.query_selector(
                    ".ui-search-official-store-label, .poly-component__seller"
                )
                store_name = await store_el.inner_text() if store_el else None
                products.append(
                    ScrapedProduct(
                        marketplace=self.marketplace,
                        external_id=external_id,
                        title=title,
                        current_price=price,
                        shipping_price=shipping,
                        condition=condition,
                        rating=rating,
                        sold_count=sold_count,
                        store_name=store_name.strip() if store_name else None,
                        url=href.split("?")[0],
                        image_url=image_url,
                        collected_at=datetime.utcnow(),
                    )
                )
        finally:
            await page_obj.close()
        return products
