import asyncio
import json
import os
import random
import urllib.error
import urllib.request
from pathlib import Path

from loguru import logger
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.config.settings import get_settings
from app.utils.browser_stealth import (
    BROWSER_LOCALE,
    BROWSER_TIMEZONE,
    BROWSER_VIEWPORT,
    CHROMIUM_IGNORE_DEFAULT_ARGS,
    DEFAULT_USER_AGENT,
    FIREFOX_USER_AGENT,
    apply_stealth,
    get_chromium_launch_args,
    should_apply_stealth,
)
from app.utils.playwright_browsers import firefox_playwright_installed, resolve_shopee_browser
from app.utils.shopee_auth import (
    shopee_profile_dir,
    shopee_session_ready,
    shopee_storage_path,
)


def cdp_endpoint_alive(cdp_url: str) -> bool:
    base = cdp_url.rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/json/version", timeout=3) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _brave_executable() -> str | None:
    candidates = [
        Path(os.environ.get("ProgramFiles", ""))
        / "BraveSoftware/Brave-Browser/Application/brave.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "BraveSoftware/Brave-Browser/Application/brave.exe",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


async def _hydrate_shopee_cookies(context: BrowserContext) -> None:
    path = shopee_storage_path()
    if not shopee_session_ready():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cookies = data.get("cookies") or []
        if cookies:
            await context.add_cookies(cookies)
            logger.info("Cookies Shopee aplicados ({} itens) de {}", len(cookies), path)
    except Exception as exc:
        logger.debug("Cookie hydrate: {}", exc)


class PlaywrightManager:
    def __init__(
        self,
        *,
        for_shopee: bool = False,
        browser_override: str | None = None,
        headless_override: bool | None = None,
        force_cdp: bool = False,
        skip_cdp: bool = False,
        use_persistent_override: bool = False,
        interactive_override: bool | None = None,
        skip_cookies_override: bool = False,
        force_stealth_override: bool | None = None,
    ) -> None:
        self._for_shopee = for_shopee
        self._browser_override = browser_override
        self._headless_override = headless_override
        self._force_cdp = force_cdp
        self._skip_cdp = skip_cdp
        self._use_persistent_override = use_persistent_override
        self._interactive_override = interactive_override
        self._skip_cookies_override = skip_cookies_override
        self._force_stealth_override = force_stealth_override
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._persistent: bool = False
        self._using_cdp: bool = False
        self._engine_label: str = ""
        self._external_browser: Browser | None = None
        self._external_context: BrowserContext | None = None

    @property
    def engine_label(self) -> str:
        return self._engine_label or "unknown"

    def _shopee_browser_choice(self, settings) -> str:
        if self._browser_override:
            return self._browser_override.lower()
        return resolve_shopee_browser(settings.shopee_browser)

    async def start(self) -> BrowserContext:
        if self._context is not None:
            return self._context
        settings = get_settings()
        self._playwright = await async_playwright().start()

        cdp = (settings.shopee_cdp_url or "http://127.0.0.1:9222").strip()
        use_cdp = False
        if self._for_shopee and not self._skip_cdp:
            if self._force_cdp:
                use_cdp = bool(cdp)
            else:
                browser = self._shopee_browser_choice(settings)
                use_cdp = bool(cdp) and cdp_endpoint_alive(cdp)
        if use_cdp:
            ctx = await self._start_cdp(cdp, settings)
            if ctx is not None:
                return ctx

        if self._for_shopee:
            browser = self._shopee_browser_choice(settings)
            eff_settings = settings
            if self._headless_override is not None:
                eff_settings = settings.model_copy(
                    update={"headless": self._headless_override}
                )
            if self._use_persistent_override:
                eff_settings = eff_settings.model_copy(
                    update={"shopee_persistent_profile": True}
                )
            if browser == "firefox":
                return await self._start_firefox(eff_settings)
            if browser == "brave":
                return await self._start_brave(eff_settings)
            if browser in ("chrome", "chromium"):
                return await self._start_chromium(eff_settings, channel=browser)

        return await self._start_chromium(settings, channel="chrome")

    async def _start_cdp(self, cdp: str, settings) -> BrowserContext | None:
        if not cdp_endpoint_alive(cdp):
            msg = (
                f"Chrome CDP offline em {cdp}. "
                "Rode scripts\\start-chrome-cdp.bat ou defina SHOPEE_BROWSER=firefox no .env"
            )
            if settings.shopee_cdp_strict:
                raise RuntimeError(msg)
            logger.warning("{}", msg)
            return None
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(cdp)
            contexts = self._browser.contexts
            self._context = (
                contexts[0] if contexts else await self._browser.new_context()
            )
            if not self._skip_cookies_override:
                await _hydrate_shopee_cookies(self._context)
            self._persistent = True
            self._using_cdp = True
            self._engine_label = f"cdp({cdp})"
            logger.info("Shopee: Chrome real via CDP {}", cdp)
            return self._context
        except Exception as exc:
            msg = f"CDP connect falhou: {exc}"
            if settings.shopee_cdp_strict:
                raise RuntimeError(msg) from exc
            logger.warning("{}, tentando outro navegador", msg)
            return None

    async def _start_firefox(self, settings) -> BrowserContext:
        try:
            self._browser = await self._playwright.firefox.launch(
                headless=settings.headless,
                firefox_user_prefs={
                    "dom.webdriver.enabled": False,
                    "useAutomationExtension": False,
                },
            )
        except Exception as exc:
            logger.warning("Firefox indisponível ({}); usando Chrome", exc)
            return await self._start_chromium(settings, channel="chrome")
        context_kwargs: dict = {
            "user_agent": FIREFOX_USER_AGENT,
            "locale": BROWSER_LOCALE,
            "timezone_id": BROWSER_TIMEZONE,
            "viewport": BROWSER_VIEWPORT,
            "extra_http_headers": {"Accept-Language": "pt-BR,pt;q=0.9"},
        }
        storage = shopee_storage_path()
        if not self._skip_cookies_override and shopee_session_ready():
            context_kwargs["storage_state"] = str(storage)
        self._context = await self._browser.new_context(**context_kwargs)
        self._engine_label = "firefox"
        logger.info(
            "Shopee: Firefox (mais parecido com usuário — rode: playwright install firefox)"
        )
        return self._context

    async def _start_brave(self, settings) -> BrowserContext:
        exe = _brave_executable()
        if not exe:
            logger.warning("Brave não encontrado; usando Chrome")
            return await self._start_chromium(settings, channel="chrome")
        launch_args = get_chromium_launch_args(
            headless=settings.headless,
            start_minimized=settings.browser_start_minimized,
        )
        self._browser = await self._playwright.chromium.launch(
            executable_path=exe,
            headless=settings.headless,
            args=launch_args,
            ignore_default_args=CHROMIUM_IGNORE_DEFAULT_ARGS,
        )
        return await self._finish_chromium_context(settings)

    async def _start_chromium(self, settings, *, channel: str) -> BrowserContext:
        launch_args = get_chromium_launch_args(
            headless=settings.headless,
            start_minimized=settings.browser_start_minimized,
        )
        profile_dir = shopee_profile_dir()
        if self._for_shopee and settings.shopee_persistent_profile and profile_dir.is_dir():
            kwargs: dict = {
                "user_data_dir": str(profile_dir),
                "headless": settings.headless,
                "locale": BROWSER_LOCALE,
                "timezone_id": BROWSER_TIMEZONE,
                "viewport": BROWSER_VIEWPORT,
                "args": launch_args,
                "ignore_default_args": CHROMIUM_IGNORE_DEFAULT_ARGS,
                "user_agent": DEFAULT_USER_AGENT,
            }
            for ch in (channel if channel == "chrome" else None, "chrome", None):
                try:
                    kw = dict(kwargs)
                    if ch:
                        kw["channel"] = ch
                    self._context = (
                        await self._playwright.chromium.launch_persistent_context(**kw)
                    )
                    self._persistent = True
                    self._engine_label = f"perfil-{ch or 'bundled'}"
                    logger.info("Shopee: perfil persistente em {}", profile_dir)
                    return self._context
                except Exception as exc:
                    logger.debug("Perfil persistente {}: {}", ch, exc)

        launch_kwargs = {
            "headless": settings.headless,
            "args": launch_args,
            "ignore_default_args": CHROMIUM_IGNORE_DEFAULT_ARGS,
        }
        if not settings.headless and channel == "chrome":
            try:
                self._browser = await self._playwright.chromium.launch(
                    channel="chrome", **launch_kwargs
                )
            except Exception:
                self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        else:
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        return await self._finish_chromium_context(settings)

    async def _finish_chromium_context(self, settings) -> BrowserContext:
        context_kwargs: dict = {
            "user_agent": DEFAULT_USER_AGENT,
            "locale": BROWSER_LOCALE,
            "timezone_id": BROWSER_TIMEZONE,
            "viewport": BROWSER_VIEWPORT,
        }
        storage = shopee_storage_path()
        if not self._skip_cookies_override and shopee_session_ready():
            context_kwargs["storage_state"] = str(storage)
            logger.info("Shopee: sessão cookies em {}", storage)
        elif self._skip_cookies_override:
            logger.info("Shopee: sem cookies (modo bot)")
        self._context = await self._browser.new_context(**context_kwargs)
        use_stealth = should_apply_stealth(
            for_shopee=self._for_shopee, cdp=self._using_cdp
        )
        if self._force_stealth_override is True:
            use_stealth = True
        elif self._force_stealth_override is False:
            use_stealth = False
        if use_stealth:
            await apply_stealth(self._context)
        self._engine_label = "chromium"
        logger.info("Shopee: Chromium/Chrome (visível={})", not settings.headless)
        return self._context

    async def new_page(self) -> Page:
        context = await self.start()
        page = await context.new_page()
        page.set_default_timeout(45000)
        return page

    async def new_page_external(self) -> Page:
        settings = get_settings()
        if self._external_context is None:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            launch_args = get_chromium_launch_args(
                headless=settings.headless,
                start_minimized=settings.browser_start_minimized,
            )
            launch_kwargs = {
                "headless": settings.headless,
                "args": launch_args,
                "ignore_default_args": CHROMIUM_IGNORE_DEFAULT_ARGS,
            }
            try:
                self._external_browser = await self._playwright.chromium.launch(
                    channel="chrome", **launch_kwargs
                )
            except Exception:
                self._external_browser = await self._playwright.chromium.launch(
                    **launch_kwargs
                )
            self._external_context = await self._external_browser.new_context(
                user_agent=DEFAULT_USER_AGENT,
                locale=BROWSER_LOCALE,
                timezone_id=BROWSER_TIMEZONE,
                viewport=BROWSER_VIEWPORT,
            )
        page = await self._external_context.new_page()
        page.set_default_timeout(30000)
        return page

    async def close(self) -> None:
        try:
            if self._context:
                await self._context.close()
        except Exception as exc:
            logger.debug("Context close ignored: {}", exc)
        finally:
            self._context = None
        try:
            if self._external_context:
                await self._external_context.close()
        except Exception as exc:
            logger.debug("External context close ignored: {}", exc)
        finally:
            self._external_context = None
        try:
            if self._external_browser:
                await self._external_browser.close()
        except Exception as exc:
            logger.debug("External browser close ignored: {}", exc)
        finally:
            self._external_browser = None
        if not self._persistent:
            try:
                if self._browser:
                    await self._browser.close()
            except Exception as exc:
                logger.debug("Browser close ignored: {}", exc)
            finally:
                self._browser = None
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception as exc:
            logger.debug("Playwright stop ignored: {}", exc)
        finally:
            self._playwright = None
            self._persistent = False
            self._using_cdp = False


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
