import asyncio
import re
import urllib.parse
from datetime import datetime

from app.config.settings import get_settings

from loguru import logger
from playwright.async_api import Page, Response

from app.config.loader import ShopeeOptionsConfig
from app.models.schemas import ScrapedProduct
from app.scrapers.base import BaseScraper
from app.utils.browser_stealth import is_shopee_blocked_html
from app.utils.playwright import auto_scroll, parse_brl_price
from app.utils.shopee_pdp import (
    SHOPEE_PDP_API,
    build_get_pc_url,
    parse_get_pc_payloads,
    parse_price_from_html,
)
from app.utils.playwright_browsers import EXTERNAL_SEARCH_STRATEGIES
from app.utils.retry import async_retry

SHOPEE_ITEM_HREF = re.compile(r"[-/]i\.(\d+)\.(\d+)")
SHOPEE_SEARCH_API = re.compile(r"/api/v4/search/search_items")


class ShopeeScraper(BaseScraper):
    marketplace = "shopee"
    _watch_products: list[ScrapedProduct] | None = None
    _last_intercept_meta: dict = {}

    @property
    def _shopee_opts(self) -> ShopeeOptionsConfig:
        return self.config.marketplaces.shopee_options

    async def _get_watch_products(self) -> list[ScrapedProduct]:
        if self._watch_products is None:
            self._watch_products = await self._scrape_watch_urls()
        return self._watch_products

    def _build_strategies(self) -> list[tuple[str, object]]:
        external: list[tuple[str, object]] = []
        if self._shopee_opts.duckduckgo_site_fallback:
            external.append(("duckduckgo_site", self._search_via_duckduckgo_site))
        if self._shopee_opts.bing_site_fallback:
            external.append(("bing_site", self._search_via_bing_site))
        if self._shopee_opts.google_site_fallback:
            external.append(("google_site", self._search_via_google_site))
        if get_settings().shopee_fallback_only:
            logger.bind(category="scraping").info(
                "Shopee: SHOPEE_FALLBACK_ONLY — usando DuckDuckGo/Bing/Google"
            )
            return external
        internal: list[tuple[str, object]] = [
            ("network_intercept", self._search_via_network_intercept),
            ("dom", self._search_via_playwright),
            ("api", self._search_via_api),
        ]
        if self._shopee_opts.prefer_external_search_first:
            return external + internal
        return internal + external

    async def _new_search_page(self, *, external: bool = False) -> Page:
        if external and self._shopee_opts.use_clean_browser_for_external:
            return await self._pw.new_page_external()
        return await self._pw.new_page()

    @async_retry(max_attempts=3, delay_seconds=2.0)
    async def search_products(self, query: str) -> list[ScrapedProduct]:
        watch = await self._get_watch_products()
        strategies = self._build_strategies()
        for name, fn in strategies:
            results = await fn(query)
            if results:
                priced = [p for p in results if p.current_price > 0]
                if name in EXTERNAL_SEARCH_STRATEGIES and not priced:
                    logger.bind(category="scraping").info(
                        "Shopee {}: {} links sem preço — ignorando, próxima estratégia",
                        name,
                        len(results),
                    )
                    from app.utils.debug_agent_log import agent_log

                    agent_log(
                        "shopee.search_products",
                        "external_discovery_skip",
                        {"query": query, "strategy": name, "count": len(results)},
                        "H6",
                    )
                    continue
                logger.bind(category="scraping").info(
                    "Shopee {} returned {} items for '{}' ({} com preço)",
                    name,
                    len(results),
                    query,
                    len(priced),
                )
                from app.utils.debug_agent_log import agent_log

                agent_log(
                    "shopee.search_products",
                    "shopee_strategy_ok",
                    {
                        "query": query,
                        "strategy": name,
                        "count": len(results),
                        "priced": len(priced),
                    },
                    "H6",
                )
                merged = self._dedupe_products(watch + results)
                return merged
            from app.utils.debug_agent_log import agent_log

            agent_log(
                "shopee.search_products",
                "shopee_strategy_miss",
                {"query": query, "strategy": name},
                "H6",
            )
        logger.bind(category="scraping").warning(
            "Shopee: nenhuma estratégia retornou itens para '{}'", query
        )
        return watch

    async def _scrape_watch_urls(self) -> list[ScrapedProduct]:
        urls = [u.strip() for u in self._shopee_opts.watch_urls if u.strip()]
        if not urls:
            return []
        out: list[ScrapedProduct] = []
        for url in urls[:20]:
            item = await self._scrape_product_url(url)
            if item:
                out.append(item)
        return out

    def _dedupe_products(self, products: list[ScrapedProduct]) -> list[ScrapedProduct]:
        seen: set[str] = set()
        out: list[ScrapedProduct] = []
        for p in products:
            key = p.external_id or p.url
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        return out

    async def _warmup_shopee(self, page: Page) -> bool:
        if not self._shopee_opts.warmup_home:
            return True
        try:
            await page.goto(
                "https://shopee.com.br/",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            html = await page.content()
            if is_shopee_blocked_html(html) or "verify/traffic" in page.url:
                return False
            await asyncio.sleep(1.5)
            return True
        except Exception as exc:
            logger.debug("Shopee warmup: {}", exc)
            return False

    async def _search_via_network_intercept(self, query: str) -> list[ScrapedProduct]:
        """Captura JSON da busca quando o próprio site chama a API (headers anti-bot)."""
        self._last_intercept_meta = {}
        encoded = urllib.parse.quote(query)
        search_url = f"https://shopee.com.br/search?keyword={encoded}"
        page = await self._pw.new_page()
        payloads: list[dict] = []

        async def on_response(response: Response) -> None:
            if response.status != 200 or not SHOPEE_SEARCH_API.search(response.url):
                return
            try:
                data = await response.json()
                if data.get("error"):
                    return
                payloads.append(data)
            except Exception:
                pass

        page.on("response", on_response)
        products: list[ScrapedProduct] = []
        final_url = ""
        try:
            if not await self._warmup_shopee(page):
                return []
            await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            final_url = page.url
            if "verify/traffic" in page.url or "captcha" in page.url.lower():
                return []
            try:
                await page.wait_for_selector(
                    "a[href*='-i.'], li[class*='shopee-search-item']",
                    timeout=15000,
                )
            except Exception:
                pass
            await auto_scroll(
                page,
                pause_ms=self.config.scraping.scroll_pause_ms,
                max_scrolls=5,
            )
            await asyncio.sleep(2.0)
            final_url = page.url
            products = self._items_from_api_payloads(payloads)
            if not products:
                products = await self._parse_products_from_dom(page)
            return products
        finally:
            from app.utils.debug_agent_log import agent_log

            blocked = bool(
                final_url
                and (
                    "captcha" in final_url.lower()
                    or "verify" in final_url.lower()
                )
            )
            self._last_intercept_meta = {
                "query": query,
                "api_payloads": len(payloads),
                "items": len(products),
                "priced": sum(1 for p in products if p.current_price > 0),
                "page_url": final_url[:220],
                "blocked": blocked,
            }
            agent_log(
                "shopee._search_via_network_intercept",
                "intercept_done",
                self._last_intercept_meta,
                "H10",
                run_id="intercept",
            )
            await page.close()

    async def _parse_site_search_page(
        self, page: Page, *, engine: str
    ) -> list[ScrapedProduct]:
        rows = await page.evaluate(
            """() => {
            const resolveHref = (raw) => {
                if (!raw) return '';
                if (raw.includes('uddg=')) {
                    const u = raw.match(/uddg=([^&]+)/);
                    if (u) try { return decodeURIComponent(u[1]); } catch (e) {}
                }
                return raw;
            };
            const out = [];
            const seen = new Set();
            const anchors = document.querySelectorAll(
                'a[href*="shopee.com.br"], a.result__a, a.result__url'
            );
            for (const a of anchors) {
                const href = resolveHref(a.href || '');
                if (!href.includes('shopee.com.br')) continue;
                const m = href.match(/[-.]i\\.(\\d+)\\.(\\d+)/);
                if (!m) continue;
                const key = m[1] + '_' + m[2];
                if (seen.has(key)) continue;
                seen.add(key);
                let title = (a.innerText || '').trim();
                const h3 = a.closest('div, li')?.querySelector('h3, .result__title');
                if (h3?.innerText) title = h3.innerText.trim();
                const block = a.closest('.result, .web-result, li, .g');
                const blockText = (block?.innerText || '').replace(/\\s+/g, ' ');
                const pm = blockText.match(/R\\$\\s*[\\d.]+(?:,[\\d]{2})?/);
                const priceText = pm ? pm[0] : '';
                if (title.length < 8) continue;
                out.push({
                    href, title, priceText,
                    shopId: m[1], itemId: m[2]
                });
            }
            return out.slice(0, 30);
        }"""
        )
        products: list[ScrapedProduct] = []
        for row in rows:
            href = (row.get("href") or "").split("?")[0]
            shop_id = str(row.get("shopId") or "")
            item_id = str(row.get("itemId") or "")
            price = parse_brl_price(row.get("priceText")) or 0.0
            products.append(
                ScrapedProduct(
                    marketplace=self.marketplace,
                    external_id=f"{shop_id}_{item_id}",
                    title=row["title"].strip(),
                    current_price=price,
                    url=href,
                    price_unknown=price <= 0,
                    collected_at=datetime.utcnow(),
                )
            )
        from app.utils.debug_agent_log import agent_log

        agent_log(
            "shopee._parse_site_search_page",
            "site_search_parse",
            {
                "engine": engine,
                "count": len(products),
                "with_price": sum(1 for p in products if p.current_price > 0),
                "page_url": page.url[:120],
            },
            "H7",
        )
        if not products:
            return []
        with_price = [p for p in products if p.current_price > 0]
        if with_price:
            return with_price
        max_enrich = self._shopee_opts.price_enrich_max_urls
        enriched = await self._enrich_prices_from_pages(products[:max_enrich])
        if enriched:
            return enriched
        if self._shopee_opts.accept_discovery_without_price and products:
            logger.bind(category="scraping").info(
                "Shopee {}: {} links sem preço (discovery)",
                engine,
                len(products),
            )
            return products[:15]
        return []

    async def _search_via_duckduckgo_site(self, query: str) -> list[ScrapedProduct]:
        q = urllib.parse.quote(f"site:shopee.com.br {query}")
        url = f"https://html.duckduckgo.com/html/?q={q}"
        page = await self._new_search_page(external=True)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            return await self._parse_site_search_page(page, engine="duckduckgo")
        finally:
            await page.close()

    async def _search_via_bing_site(self, query: str) -> list[ScrapedProduct]:
        q = urllib.parse.quote(f"site:shopee.com.br {query}")
        url = f"https://www.bing.com/search?q={q}&setlang=pt-br"
        page = await self._new_search_page(external=True)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            content = await page.content()
            if "captcha" in content.lower():
                return []
            return await self._parse_site_search_page(page, engine="bing")
        finally:
            await page.close()

    async def _search_via_google_site(self, query: str) -> list[ScrapedProduct]:
        """Busca Google site:shopee.com.br quando Shopee bloqueia automação."""
        q = urllib.parse.quote(f"site:shopee.com.br {query}")
        url = f"https://www.google.com/search?q={q}&hl=pt-BR&gl=br&num=30"
        page = await self._new_search_page(external=True)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            content = await page.content()
            if "captcha" in content.lower() or "/sorry/" in page.url:
                return []
            return await self._parse_site_search_page(page, engine="google")
        finally:
            await page.close()

    async def _enrich_prices_from_pages(
        self, products: list[ScrapedProduct]
    ) -> list[ScrapedProduct]:
        enriched: list[ScrapedProduct] = []
        for p in products:
            detail = await self._scrape_product_url(p.url, fallback_title=p.title)
            if detail and detail.current_price > 0:
                enriched.append(detail)
            elif p.current_price > 0:
                enriched.append(p)
        # region agent log
        from app.utils.debug_agent_log import agent_log

        agent_log(
            "shopee._enrich_prices_from_pages",
            "enrich_result",
            {
                "input": len(products),
                "with_price": len(enriched),
            },
            "H9",
        )
        # endregion
        return enriched

    def _product_from_pdp(
        self,
        parsed: dict,
        *,
        shop_id: str,
        item_id: str,
        url: str,
        fallback_title: str = "",
    ) -> ScrapedProduct | None:
        price = parsed.get("current_price")
        if not price or price <= 0:
            return None
        title = (parsed.get("title") or fallback_title or "").strip()
        if not title:
            title = f"Shopee {shop_id}.{item_id}"
        original = parsed.get("original_price")
        discount = None
        if original and original > price:
            discount = round((1 - price / original) * 100, 1)
        image = parsed.get("image")
        image_url = f"https://cf.shopee.com.br/file/{image}" if image else None
        return ScrapedProduct(
            marketplace=self.marketplace,
            external_id=f"{shop_id}_{item_id}",
            title=title,
            current_price=float(price),
            original_price=float(original) if original else None,
            discount_percent=discount,
            url=url.split("?")[0],
            image_url=image_url,
            price_unknown=False,
            collected_at=datetime.utcnow(),
        )

    async def _maybe_wait_user_captcha(self, page: Page, *, blocked: bool) -> None:
        settings = get_settings()
        interactive = settings.shopee_interactive
        if getattr(self._pw, "_interactive_override", None) is not None:
            interactive = bool(self._pw._interactive_override)
        if not blocked or settings.headless or not interactive:
            return
        print(
            "\n>>> Shopee: resolva captcha/login na janela do navegador "
            "(Firefox/Chrome visível).\n>>> Quando o preço aparecer na página, "
            "pressione ENTER aqui.\n"
        )
        await asyncio.to_thread(input)
        await page.reload(wait_until="domcontentloaded", timeout=90000)

    async def _scrape_product_url(
        self, url: str, *, fallback_title: str = ""
    ) -> ScrapedProduct | None:
        match = SHOPEE_ITEM_HREF.search(url)
        if not match:
            return None
        shop_id, item_id = match.group(1), match.group(2)
        clean_url = url.split("?")[0]
        api_url = build_get_pc_url(shop_id, item_id)
        page = await self._pw.new_page()
        payloads: list[dict] = []

        async def on_response(response: Response) -> None:
            if response.status != 200 or not SHOPEE_PDP_API.search(response.url):
                return
            try:
                data = await response.json()
                if not data.get("error"):
                    payloads.append(data)
            except Exception:
                pass

        page.on("response", on_response)
        wait_until = self._shopee_opts.product_page_wait_until
        price_visible = False
        try:
            try:
                async with page.expect_response(
                    lambda r: SHOPEE_PDP_API.search(r.url) and r.status == 200,
                    timeout=50000,
                ):
                    await page.goto(clean_url, wait_until=wait_until, timeout=90000)
            except Exception:
                await page.goto(clean_url, wait_until=wait_until, timeout=90000)
            try:
                await page.wait_for_selector(
                    "[class*='pqTWkA'], .IZPe5B, [class*='product-price'], "
                    "[itemprop='price'], div[class*='price']",
                    timeout=22000,
                    state="visible",
                )
                price_visible = True
            except Exception:
                await page.evaluate("window.scrollTo(0, 400)")
            html = await page.content()
            blocked = is_shopee_blocked_html(html)
            if blocked:
                await self._maybe_wait_user_captcha(page, blocked=True)
                html = await page.content()
                blocked = is_shopee_blocked_html(html)
            if not payloads:
                try:
                    resp = await page.request.get(
                        api_url,
                        headers={
                            "Accept": "application/json",
                            "Referer": clean_url,
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    )
                    if resp.status == 200:
                        data = await resp.json()
                        if not data.get("error"):
                            payloads.append(data)
                except Exception as exc:
                    logger.debug("Shopee get_pc request {}: {}", api_url[:80], exc)
            parsed = parse_get_pc_payloads(payloads)
            if parsed:
                product = self._product_from_pdp(
                    parsed,
                    shop_id=shop_id,
                    item_id=item_id,
                    url=clean_url,
                    fallback_title=fallback_title,
                )
                if product:
                    # region agent log
                    from app.utils.debug_agent_log import agent_log

                    agent_log(
                        "shopee._scrape_product_url",
                        "pdp_api_ok",
                        {
                            "shop_id": shop_id,
                            "item_id": item_id,
                            "price": product.current_price,
                            "blocked": blocked,
                        },
                        "H9",
                    )
                    # endregion
                    return product
            if not blocked:
                html_parsed = parse_price_from_html(html)
                if html_parsed:
                    product = self._product_from_pdp(
                        html_parsed,
                        shop_id=shop_id,
                        item_id=item_id,
                        url=clean_url,
                        fallback_title=fallback_title or (await page.title()),
                    )
                    if product:
                        from app.utils.debug_agent_log import agent_log

                        agent_log(
                            "shopee._scrape_product_url",
                            "pdp_html_ok",
                            {"price": product.current_price},
                            "H9",
                        )
                        return product
                price_text = await page.evaluate(
                    """() => {
                    const sel = [
                        '[class*="pqTWkA"]', '.IZPe5B', '[class*="price"]',
                        'div[class*="product-price"]'
                    ];
                    for (const s of sel) {
                        const el = document.querySelector(s);
                        if (el && el.innerText && el.innerText.includes('R$'))
                            return el.innerText;
                    }
                    return '';
                }"""
                )
                dom_price = parse_brl_price(price_text)
                if dom_price:
                    title = (await page.title()).split("|")[0].strip()
                    return ScrapedProduct(
                        marketplace=self.marketplace,
                        external_id=f"{shop_id}_{item_id}",
                        title=fallback_title or title or f"Shopee {shop_id}.{item_id}",
                        current_price=dom_price,
                        url=clean_url,
                        price_unknown=False,
                        collected_at=datetime.utcnow(),
                    )
            # region agent log
            from app.utils.debug_agent_log import agent_log

            agent_log(
                "shopee._scrape_product_url",
                "pdp_miss",
                {
                    "url": clean_url[:100],
                    "blocked": blocked,
                    "payloads": len(payloads),
                    "price_visible": price_visible,
                },
                "H9",
            )
            # endregion
            return None
        except Exception as exc:
            logger.debug("Shopee product URL {}: {}", url[:80], exc)
            return None
        finally:
            await page.close()

    def _items_from_api_payloads(self, payloads: list[dict]) -> list[ScrapedProduct]:
        products: list[ScrapedProduct] = []
        seen: set[str] = set()
        for data in payloads:
            for entry in data.get("items") or []:
                item_basic = entry.get("item_basic") or entry
                parsed = self._parse_api_item(item_basic)
                if not parsed:
                    continue
                if parsed.external_id in seen:
                    continue
                seen.add(parsed.external_id)
                products.append(parsed)
        return products

    async def _search_via_api(self, query: str) -> list[ScrapedProduct]:
        encoded = urllib.parse.quote(query)
        api_url = (
            "https://shopee.com.br/api/v4/search/search_items"
            f"?keyword={encoded}&limit=50&newest=0&order=desc&page_type=search"
            "&scenario=PAGE_GLOBAL_SEARCH"
        )
        search_url = f"https://shopee.com.br/search?keyword={encoded}"
        page = await self._pw.new_page()
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_selector(
                    "a[href*='-i.'], [class*='shopee-search-item']",
                    timeout=12000,
                )
            except Exception:
                logger.bind(category="scraping").debug(
                    "Shopee search page: selector timeout before API call for '{}'", query
                )
            response = await page.request.get(
                api_url,
                headers={
                    "Accept": "application/json",
                    "Referer": search_url,
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            # region agent log
            from app.utils.debug_agent_log import agent_log

            agent_log(
                "shopee._search_via_api",
                "shopee_api_status",
                {"query": query, "http_status": response.status},
                "H3",
            )
            # endregion
            if response.status != 200:
                return []
            data = await response.json()
            items = data.get("items") or []
            # region agent log
            agent_log(
                "shopee._search_via_api",
                "shopee_api_items",
                {"query": query, "items_count": len(items)},
                "H3",
            )
            # endregion
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

    def _is_out_of_stock_item(self, item: dict) -> bool:
        if not self._shopee_opts.skip_out_of_stock:
            return False
        stock = item.get("stock")
        if stock is not None and int(stock) <= 0:
            return True
        if item.get("is_sold_out") or item.get("sold_out"):
            return True
        status = item.get("item_status")
        if isinstance(status, str) and "sold" in status.lower():
            return True
        return False

    def _parse_api_item(self, item: dict) -> ScrapedProduct | None:
        item_id = item.get("itemid") or item.get("item_id")
        shop_id = item.get("shopid") or item.get("shop_id")
        if not item_id or not shop_id:
            return None
        if self._is_out_of_stock_item(item):
            return None
        title = item.get("name") or ""
        if not title:
            return None
        price_raw = item.get("price") or item.get("price_min") or 0
        price = float(price_raw) / 100000 if price_raw > 10000 else float(price_raw)
        if price <= 0:
            return None
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
        product_url = f"https://shopee.com.br/{slug}-i.{shop_id}.{item_id}"
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
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            current_url = page.url
            if "verify/traffic" in current_url or "captcha" in current_url.lower():
                logger.bind(category="scraping").warning(
                    "Shopee bloqueou acesso (captcha/verificação) para '{}' — tente HEADLESS=false no .env",
                    query,
                )
                # region agent log
                from app.utils.debug_agent_log import agent_log

                agent_log(
                    "shopee._search_via_playwright",
                    "shopee_blocked",
                    {"query": query, "page_url": current_url[:220]},
                    "H4",
                )
                # endregion
                return []
            try:
                await page.wait_for_selector(
                    "li[class*='shopee-search-item'], a[href*='-i.']",
                    timeout=15000,
                )
            except Exception:
                logger.bind(category="scraping").warning(
                    "Shopee: lista de produtos não carregou a tempo para '{}'", query
                )
            await auto_scroll(
                page,
                pause_ms=self.config.scraping.scroll_pause_ms,
                max_scrolls=4,
            )
            products = await self._parse_products_from_dom(page)
            if not products:
                products = await self._parse_products_legacy_selectors(page)
        finally:
            if len(products) == 0:
                from app.utils.debug_agent_log import log_page_scrape_diagnostic

                await log_page_scrape_diagnostic(
                    page,
                    marketplace="shopee",
                    query=query,
                    items_parsed=0,
                    extra={"wait_until": "domcontentloaded"},
                )
            await page.close()
        return products

    async def _parse_products_from_dom(self, page: Page) -> list[ScrapedProduct]:
        rows = await page.evaluate(
            """() => {
            const seen = new Set();
            const out = [];
            const items = document.querySelectorAll(
                "li[class*='shopee-search-item-result__item'], li.shopee-search-item-result__item"
            );
            const parseCard = (card) => {
                const a = card.querySelector("a[href]");
                if (!a) return null;
                const href = a.href || "";
                const idMatch = href.match(/[-.]i\\.(\\d+)\\.(\\d+)/)
                    || href.match(/\\.(\\d{6,})\\.(\\d{6,})/);
                if (!idMatch) return null;
                const key = idMatch[1] + "_" + idMatch[2];
                if (seen.has(key)) return null;
                seen.add(key);
                const t = card.querySelector(
                    "[class*='title'], [class*='name'], [class*='line-clamp']"
                );
                const title = (t?.innerText || a.innerText || "").trim();
                const p = card.querySelector("[class*='price'], span[class*='currency']");
                const priceText = (p?.innerText || "").trim();
                const cardText = (card.innerText || "").toLowerCase();
                if (cardText.includes('esgotado') || cardText.includes('indisponível')
                    || cardText.includes('indisponivel')) return null;
                if (title.length < 8) return null;
                return { href, title, priceText, shopId: idMatch[1], itemId: idMatch[2] };
            };
            for (const card of items) {
                const row = parseCard(card);
                if (row) out.push(row);
            }
            if (out.length === 0) {
                for (const a of document.querySelectorAll("a[href]")) {
                    const href = a.href || "";
                    const idMatch = href.match(/[-.]i\\.(\\d+)\\.(\\d+)/);
                    if (!idMatch) continue;
                    const key = idMatch[1] + "_" + idMatch[2];
                    if (seen.has(key)) continue;
                    seen.add(key);
                    const card = a.closest("li") || a.parentElement;
                    const t = card?.querySelector("[class*='title'], [class*='name']");
                    const title = (t?.innerText || a.innerText || "").trim();
                    const p = card?.querySelector("[class*='price']");
                    const priceText = (p?.innerText || "").trim();
                    if (title.length < 8) continue;
                    out.push({
                        href, title, priceText,
                        shopId: idMatch[1], itemId: idMatch[2]
                    });
                }
            }
            return out.slice(0, 50);
        }"""
        )
        products: list[ScrapedProduct] = []
        for row in rows:
            href = row.get("href") or ""
            shop_id = str(row.get("shopId") or "")
            item_id = str(row.get("itemId") or "")
            match = SHOPEE_ITEM_HREF.search(href)
            if match:
                shop_id, item_id = match.group(1), match.group(2)
            if not shop_id or not item_id:
                continue
            price = parse_brl_price(row.get("priceText"))
            if not price:
                continue
            products.append(
                ScrapedProduct(
                    marketplace=self.marketplace,
                    external_id=f"{shop_id}_{item_id}",
                    title=row["title"].strip(),
                    current_price=price,
                    url=href.split("?")[0],
                    collected_at=datetime.utcnow(),
                )
            )
        return products

    async def _parse_products_legacy_selectors(self, page: Page) -> list[ScrapedProduct]:
        products: list[ScrapedProduct] = []
        cards = await page.query_selector_all(
            "div[class*='shopee-search-item-result'] a, "
            "li.shopee-search-item-result__item a, "
            "div[class*='shop-search-result-view'] a[href*='-i.']"
        )
        seen: set[str] = set()
        for card in cards[:40]:
            href = await card.get_attribute("href")
            if not href or href in seen:
                continue
            seen.add(href)
            full_url = href if href.startswith("http") else f"https://shopee.com.br{href}"
            ext_match = SHOPEE_ITEM_HREF.search(href)
            if not ext_match:
                continue
            parent = await card.evaluate_handle(
                "el => el.closest('li') || el.parentElement"
            )
            parent_el = parent.as_element()
            if not parent_el:
                continue
            title_el = await parent_el.query_selector(
                "div[class*='title'], div[class*='name'], .ie3A\\+n"
            )
            price_el = await parent_el.query_selector(
                "span[class*='price'], .ZEgDH9, [class*='currency']"
            )
            title = (await title_el.inner_text()) if title_el else ""
            price_text = (await price_el.inner_text()) if price_el else ""
            price = parse_brl_price(price_text)
            if not title or not price:
                continue
            products.append(
                ScrapedProduct(
                    marketplace=self.marketplace,
                    external_id=f"{ext_match.group(1)}_{ext_match.group(2)}",
                    title=title.strip(),
                    current_price=price,
                    url=full_url,
                    collected_at=datetime.utcnow(),
                )
            )
        return products
