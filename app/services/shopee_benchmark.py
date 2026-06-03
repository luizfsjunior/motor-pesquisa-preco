"""Benchmark Shopee: testa navegadores e estratégias do melhor ao pior."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from loguru import logger

from app.config.loader import AppConfig, load_app_config
from app.config.settings import PROJECT_ROOT, get_settings
from app.scrapers.shopee import ShopeeScraper
from app.utils.debug_agent_log import agent_log
from app.utils.playwright import PlaywrightManager, cdp_endpoint_alive
from app.utils.shopee_auth import shopee_profile_dir

DEFAULT_PRODUCT_URL = (
    "https://shopee.com.br/Console-Nintendo-Switch-2-256GB-LCD-Gray-Novo-Lacrado-"
    "Lan%C3%A7amento-vai-com-adaptador-de-tomada.-i.1306226862.22294202875"
)
REPORT_PATH = PROJECT_ROOT / "data" / "shopee_benchmark_report.json"


@dataclass(frozen=True)
class BenchCase:
    case_id: str
    label: str
    tier: int
    test_kind: str
    browser: str = "firefox"
    headless: bool = False
    force_cdp: bool = False
    skip_cdp: bool = True
    use_persistent: bool = False
    strategy: str | None = None
    needs_interactive: bool = False
    notes: str = ""


@dataclass
class BenchResult:
    case_id: str
    label: str
    tier: int
    test_kind: str
    ok: bool
    score: int
    items: int = 0
    priced: int = 0
    min_price: float | None = None
    blocked: bool = False
    error: str | None = None
    elapsed_ms: int = 0
    skipped: bool = False
    skip_reason: str = ""
    sample_title: str = ""


def build_benchmark_cases(*, include_interactive: bool) -> list[BenchCase]:
    cdp_url = (get_settings().shopee_cdp_url or "").strip()
    cdp_online = bool(cdp_url) and cdp_endpoint_alive(cdp_url)
    has_profile = shopee_profile_dir().is_dir()

    cases: list[BenchCase] = [
        BenchCase(
            "01_cdp_chrome",
            "Chrome real via CDP (porta 9222)",
            1,
            "product",
            force_cdp=True,
            skip_cdp=False,
            notes="Rode scripts/start-chrome-cdp.bat antes",
        ),
        BenchCase(
            "02_firefox_visivel",
            "Firefox visível + cookies",
            2,
            "product",
            browser="firefox",
            headless=False,
        ),
        BenchCase(
            "03_brave_visivel",
            "Brave visível + cookies",
            3,
            "product",
            browser="brave",
            headless=False,
            notes="Pula se Brave não instalado",
        ),
        BenchCase(
            "04_chrome_visivel",
            "Google Chrome visível + cookies",
            4,
            "product",
            browser="chrome",
            headless=False,
        ),
        BenchCase(
            "05_chrome_perfil",
            "Chrome perfil persistente data/shopee_browser_profile",
            5,
            "product",
            browser="chrome",
            use_persistent=True,
            notes="Rode shopee-login antes" if not has_profile else "",
        ),
        BenchCase(
            "06_firefox_interativo",
            "Firefox + pausa captcha (ENTER)",
            6,
            "product",
            browser="firefox",
            needs_interactive=True,
            notes="Resolva captcha na janela",
        ),
        BenchCase(
            "07_chromium_visivel",
            "Chromium Playwright visível",
            7,
            "product",
            browser="chromium",
            headless=False,
        ),
        BenchCase(
            "08_firefox_headless",
            "Firefox headless (servidor)",
            8,
            "product",
            browser="firefox",
            headless=True,
        ),
        BenchCase(
            "09_chrome_headless",
            "Chrome headless",
            9,
            "product",
            browser="chrome",
            headless=True,
        ),
        BenchCase(
            "10_ddg_firefox_enrich",
            "DuckDuckGo + abrir produtos (Firefox)",
            10,
            "search_enrich",
            browser="firefox",
            strategy="duckduckgo_site",
        ),
        BenchCase(
            "11_ddg_chrome_enrich",
            "DuckDuckGo + abrir produtos (Chrome)",
            11,
            "search_enrich",
            browser="chrome",
            strategy="duckduckgo_site",
        ),
        BenchCase(
            "12_ddg_links_only",
            "DuckDuckGo só links (sem preço)",
            12,
            "strategy",
            strategy="duckduckgo_site",
        ),
        BenchCase(
            "13_intercept_firefox",
            "Intercept API busca (Firefox)",
            13,
            "strategy",
            browser="firefox",
            strategy="network_intercept",
        ),
        BenchCase(
            "14_intercept_chrome",
            "Intercept API busca (Chrome)",
            14,
            "strategy",
            browser="chrome",
            strategy="network_intercept",
        ),
        BenchCase(
            "15_dom_chrome",
            "HTML busca Shopee (Chrome)",
            15,
            "strategy",
            browser="chrome",
            strategy="dom",
        ),
        BenchCase(
            "16_api_chrome",
            "API search_items direta (Chrome)",
            16,
            "strategy",
            browser="chrome",
            strategy="api",
        ),
        BenchCase(
            "17_bing_links",
            "Bing site:shopee.com.br",
            17,
            "strategy",
            strategy="bing_site",
        ),
        BenchCase(
            "18_google_links",
            "Google site:shopee.com.br",
            18,
            "strategy",
            strategy="google_site",
        ),
        BenchCase(
            "19_pipeline_firefox",
            "Pipeline completo (ordem YAML, Firefox)",
            19,
            "full_search",
            browser="firefox",
        ),
        BenchCase(
            "20_pipeline_chrome",
            "Pipeline completo (ordem YAML, Chrome)",
            20,
            "full_search",
            browser="chrome",
        ),
    ]
    if not cdp_online:
        for i, c in enumerate(cases):
            if c.case_id == "01_cdp_chrome":
                cases[i] = BenchCase(
                    c.case_id,
                    c.label,
                    c.tier,
                    c.test_kind,
                    browser=c.browser,
                    headless=c.headless,
                    force_cdp=c.force_cdp,
                    skip_cdp=c.skip_cdp,
                    use_persistent=c.use_persistent,
                    strategy=c.strategy,
                    needs_interactive=c.needs_interactive,
                    notes="CDP offline — rode start-chrome-cdp.bat",
                )
                break
    if not include_interactive:
        return [c for c in cases if not c.needs_interactive]
    return cases


def _score_result(
    items: list, *, blocked: bool, error: str | None
) -> tuple[int, int, int, float | None]:
    priced = [i for i in items if i.current_price and i.current_price > 0]
    min_price = min((p.current_price for p in priced), default=None)
    score = 0
    if error:
        score = 0
    elif priced:
        score = 50 + len(priced) * 8 + (20 if min_price and min_price < 5000 else 0)
    elif items:
        score = 15 + len(items) * 3
    if blocked:
        score = max(0, score - 25)
    return score, len(items), len(priced), min_price


class ShopeeBenchmarkRunner:
    def __init__(
        self,
        config: AppConfig,
        *,
        product_url: str,
        query: str,
        include_interactive: bool,
        quick: bool = False,
    ) -> None:
        self.config = config
        self.product_url = product_url
        self.query = query
        self.include_interactive = include_interactive
        self.quick = quick
        self.results: list[BenchResult] = []

    def _pw(self, case: BenchCase) -> PlaywrightManager:
        interactive = None
        if case.needs_interactive and self.include_interactive:
            interactive = True
        return PlaywrightManager(
            for_shopee=True,
            browser_override=case.browser,
            headless_override=case.headless,
            force_cdp=case.force_cdp,
            skip_cdp=case.skip_cdp,
            use_persistent_override=case.use_persistent,
            interactive_override=interactive,
        )

    async def run_all(self) -> list[BenchResult]:
        cases = build_benchmark_cases(include_interactive=self.include_interactive)
        if self.quick:
            cases = [c for c in cases if c.tier <= 10]
        settings = get_settings()
        typer_note = (
            f"CDP configurado: {settings.shopee_cdp_url or '(vazio)'} | "
            f"CDP online: {cdp_endpoint_alive(settings.shopee_cdp_url or '') if settings.shopee_cdp_url else False}"
        )
        logger.info(typer_note)

        for idx, case in enumerate(cases, start=1):
            logger.info(
                "[{}/{}] Teste {} — {}",
                idx,
                len(cases),
                case.case_id,
                case.label,
            )
            result = await self._run_case(case)
            self.results.append(result)
            agent_log(
                "shopee_benchmark.run_case",
                "bench_result",
                {**asdict(result)},
                "BENCH",
                run_id="benchmark",
            )

        self.results.sort(key=lambda r: (-r.score, r.tier, r.case_id))
        self._save_report()
        return self.results

    async def _run_case(self, case: BenchCase) -> BenchResult:
        t0 = time.perf_counter()
        if case.needs_interactive and not self.include_interactive:
            return BenchResult(
                case_id=case.case_id,
                label=case.label,
                tier=case.tier,
                test_kind=case.test_kind,
                ok=False,
                score=0,
                skipped=True,
                skip_reason="Use --include-interactive",
                elapsed_ms=0,
            )
        if case.case_id == "01_cdp_chrome":
            cdp = (get_settings().shopee_cdp_url or "http://127.0.0.1:9222").strip()
            if not cdp_endpoint_alive(cdp):
                return BenchResult(
                    case_id=case.case_id,
                    label=case.label,
                    tier=case.tier,
                    test_kind=case.test_kind,
                    ok=False,
                    score=0,
                    skipped=True,
                    skip_reason="CDP offline",
                    elapsed_ms=int((time.perf_counter() - t0) * 1000),
                )

        pw = self._pw(case)
        scraper = ShopeeScraper(self.config, pw)
        items: list = []
        blocked = False
        err: str | None = None
        try:
            if case.test_kind == "product":
                item = await scraper._scrape_product_url(self.product_url)
                if item:
                    items = [item]
                    blocked = item.current_price <= 0
            elif case.test_kind == "search_enrich":
                raw = await self._run_strategy(scraper, "duckduckgo_site")
                items = await scraper._enrich_prices_from_pages(
                    raw[: self.config.marketplaces.shopee_options.price_enrich_max_urls]
                )
                if not items:
                    items = raw
            elif case.test_kind == "strategy" and case.strategy:
                items = await self._run_strategy(scraper, case.strategy)
            elif case.test_kind == "full_search":
                items = await scraper.search_products(self.query)
            else:
                err = f"test_kind desconhecido: {case.test_kind}"
        except Exception as exc:
            err = str(exc)[:300]
            logger.warning("Benchmark {} falhou: {}", case.case_id, exc)
        finally:
            await scraper.close()

        elapsed = int((time.perf_counter() - t0) * 1000)
        score, n_items, n_priced, min_p = _score_result(items, blocked=blocked, error=err)
        sample = items[0].title[:60] if items else ""
        if items and items[0].current_price <= 0:
            blocked = True

        return BenchResult(
            case_id=case.case_id,
            label=case.label,
            tier=case.tier,
            test_kind=case.test_kind,
            ok=n_priced > 0 and err is None,
            score=score,
            items=n_items,
            priced=n_priced,
            min_price=min_p,
            blocked=blocked,
            error=err,
            elapsed_ms=elapsed,
            sample_title=sample,
        )

    async def _run_strategy(self, scraper: ShopeeScraper, name: str) -> list:
        for sname, fn in scraper._build_strategies():
            if sname == name:
                return await fn(self.query)
        return []

    def _save_report(self) -> None:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "product_url": self.product_url,
            "query": self.query,
            "ranked": [asdict(r) for r in self.results],
        }
        REPORT_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def format_table(self) -> str:
        lines = [
            "",
            "=" * 72,
            " SHOPEE BENCHMARK — ranking (maior score = melhor)",
            f" Produto: {self.product_url[:65]}...",
            f" Busca:   {self.query}",
            "=" * 72,
            f"{'#':>3} {'Score':>5} {'R$':>8} {'Itens':>5} {'Preço':>5}  {'ID':<22} Label",
            "-" * 72,
        ]
        for i, r in enumerate(self.results, start=1):
            if r.skipped:
                lines.append(
                    f"{i:>3} {'SKIP':>5} {'—':>8} {'—':>5} {'—':>5}  {r.case_id:<22} {r.skip_reason}"
                )
                continue
            price = f"{r.min_price:7.0f}" if r.min_price else "   —"
            flag = "OK" if r.ok else "—"
            lines.append(
                f"{i:>3} {r.score:>5} {price:>8} {r.items:>5} {r.priced:>5}  "
                f"{r.case_id:<22} {r.label[:28]}"
            )
            if r.error:
                lines.append(f"      erro: {r.error[:60]}")
        lines.append("-" * 72)
        lines.append(f" Relatório JSON: {REPORT_PATH}")
        lines.append(" Configure o vencedor no .env (SHOPEE_BROWSER / SHOPEE_CDP_URL)")
        lines.append("")
        return "\n".join(lines)
