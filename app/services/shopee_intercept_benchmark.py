"""Benchmark network_intercept: sessão do mais bot ao mais humano (alternativas ao CDP)."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger

from app.config.loader import AppConfig, load_app_config
from app.config.settings import PROJECT_ROOT, get_settings
from app.scrapers.shopee import ShopeeScraper
from app.utils.debug_agent_log import agent_log
from app.utils.playwright import PlaywrightManager, cdp_endpoint_alive
from app.utils.playwright_browsers import firefox_playwright_installed, resolve_shopee_browser
from app.utils.shopee_auth import shopee_profile_dir, shopee_session_ready

JSON_REPORT = PROJECT_ROOT / "data" / "shopee_intercept_benchmark.json"
TEXT_LOG = PROJECT_ROOT / "data" / "shopee_intercept_benchmark.log"


@dataclass(frozen=True)
class InterceptSessionCase:
    case_id: str
    label: str
    humanity: int
    browser: str = "chromium"
    headless: bool = True
    skip_cdp: bool = True
    force_cdp: bool = False
    skip_cookies: bool = False
    force_stealth: bool | None = None
    use_persistent: bool = False
    notes: str = ""


@dataclass
class InterceptSessionResult:
    case_id: str
    label: str
    humanity: int
    engine: str
    ok: bool
    score: int
    items: int = 0
    priced: int = 0
    min_price: float | None = None
    api_payloads: int = 0
    blocked: bool = False
    page_url: str = ""
    cookies_used: bool = False
    error: str | None = None
    elapsed_ms: int = 0
    skipped: bool = False
    skip_reason: str = ""


def build_intercept_session_cases() -> list[InterceptSessionCase]:
    cdp_url = (get_settings().shopee_cdp_url or "http://127.0.0.1:9222").strip()
    cdp_online = cdp_endpoint_alive(cdp_url)
    has_profile = shopee_profile_dir().is_dir()
    has_cookies = shopee_session_ready()

    cases: list[InterceptSessionCase] = [
        InterceptSessionCase(
            "01_bot_chromium_headless_raw",
            "Chromium headless — zero sessão (máximo bot)",
            1,
            browser="chromium",
            headless=True,
            skip_cookies=True,
            notes="Sem cookies, sem stealth Shopee",
        ),
        InterceptSessionCase(
            "02_bot_chromium_headless_stealth",
            "Chromium headless + script anti-webdriver",
            2,
            browser="chromium",
            headless=True,
            skip_cookies=True,
            force_stealth=True,
            notes="Stealth ligado de propósito",
        ),
        InterceptSessionCase(
            "03_bot_chromium_headless_cookies",
            "Chromium headless + cookies salvos",
            3,
            browser="chromium",
            headless=True,
            skip_cookies=False,
            notes="" if has_cookies else "Sem data/shopee_storage_state.json",
        ),
        InterceptSessionCase(
            "04_chrome_headless_cookies",
            "Chrome headless + cookies",
            4,
            browser="chrome",
            headless=True,
        ),
        InterceptSessionCase(
            "05_chrome_visible_cookies",
            "Chrome visível + cookies",
            5,
            browser="chrome",
            headless=False,
        ),
        InterceptSessionCase(
            "06_chromium_visible_cookies",
            "Chromium visível + cookies",
            6,
            browser="chromium",
            headless=False,
        ),
        InterceptSessionCase(
            "07_chrome_persistent_profile",
            "Chrome perfil persistente (shopee-login)",
            7,
            browser="chrome",
            headless=False,
            use_persistent=True,
            notes="Rode shopee-login antes" if not has_profile else "",
        ),
        InterceptSessionCase(
            "08_brave_visible_cookies",
            "Brave visível + cookies",
            8,
            browser="brave",
            headless=False,
        ),
        InterceptSessionCase(
            "09_firefox_visible_cookies",
            "Firefox visível + cookies",
            9,
            browser="firefox",
            headless=False,
            notes="Pula se Firefox Playwright não instalado",
        ),
        InterceptSessionCase(
            "10_cdp_chrome_logged",
            "Chrome real via CDP (mais humano)",
            10,
            browser="chrome",
            headless=False,
            skip_cdp=False,
            force_cdp=True,
            notes="Rode start-chrome-cdp.bat + login Shopee"
            if cdp_online
            else "CDP offline",
        ),
    ]
    return cases


def _score(items: list, *, blocked: bool, error: str | None) -> tuple[int, int, float | None]:
    priced = [i for i in items if i.current_price and i.current_price > 0]
    min_p = min((p.current_price for p in priced), default=None)
    score = 0
    if error:
        score = 0
    elif priced:
        score = 50 + len(priced) * 5 + (15 if min_p and min_p < 5000 else 0)
    elif items:
        score = 10
    if blocked:
        score = max(0, score - 20)
    return score, len(priced), min_p


class ShopeeInterceptBenchmarkRunner:
    def __init__(self, config: AppConfig, *, query: str) -> None:
        self.config = config
        self.query = query
        self.results: list[InterceptSessionResult] = []

    def _pw(self, case: InterceptSessionCase) -> PlaywrightManager:
        return PlaywrightManager(
            for_shopee=True,
            browser_override=case.browser,
            headless_override=case.headless,
            force_cdp=case.force_cdp,
            skip_cdp=case.skip_cdp,
            use_persistent_override=case.use_persistent,
            skip_cookies_override=case.skip_cookies,
            force_stealth_override=case.force_stealth,
        )

    async def run_all(self) -> list[InterceptSessionResult]:
        cases = build_intercept_session_cases()
        self._append_log_header(len(cases))

        for idx, case in enumerate(cases, start=1):
            line = f"[{idx:02d}/{len(cases)}] humanidade {case.humanity}/10 — {case.case_id}"
            logger.info("{} — {}", line, case.label)
            result = await self._run_case(case)
            self.results.append(result)
            self._append_case_log(result, case)
            agent_log(
                "shopee_intercept_benchmark.run_case",
                "intercept_session_result",
                {**asdict(result), "notes": case.notes},
                "H10",
                run_id="intercept-benchmark",
            )

        self._save_json()
        self._append_summary()
        return self.results

    async def _run_case(self, case: InterceptSessionCase) -> InterceptSessionResult:
        t0 = time.perf_counter()
        if case.case_id == "10_cdp_chrome_logged":
            cdp = (get_settings().shopee_cdp_url or "http://127.0.0.1:9222").strip()
            if not cdp_endpoint_alive(cdp):
                return InterceptSessionResult(
                    case_id=case.case_id,
                    label=case.label,
                    humanity=case.humanity,
                    engine="cdp-offline",
                    ok=False,
                    score=0,
                    skipped=True,
                    skip_reason="CDP offline — start-chrome-cdp.bat",
                    elapsed_ms=int((time.perf_counter() - t0) * 1000),
                )
        if case.browser == "firefox" and not firefox_playwright_installed():
            return InterceptSessionResult(
                case_id=case.case_id,
                label=case.label,
                humanity=case.humanity,
                engine="firefox-missing",
                ok=False,
                score=0,
                skipped=True,
                skip_reason="playwright install firefox",
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
            )

        pw = self._pw(case)
        scraper = ShopeeScraper(self.config, pw)
        items: list = []
        err: str | None = None
        engine = "pending"
        try:
            await pw.start()
            engine = pw.engine_label
            items = await scraper._search_via_network_intercept(self.query)
        except Exception as exc:
            err = str(exc)[:400]
            engine = pw.engine_label
            logger.warning("Intercept benchmark {}: {}", case.case_id, exc)
        finally:
            await scraper.close()

        elapsed = int((time.perf_counter() - t0) * 1000)
        meta = getattr(scraper, "_last_intercept_meta", {}) or {}
        blocked = bool(meta.get("blocked"))
        page_url = str(meta.get("page_url") or "")
        api_payloads = int(meta.get("api_payloads") or 0)
        score, n_priced, min_p = _score(items, blocked=blocked, error=err)
        cookies_used = not case.skip_cookies and shopee_session_ready()

        return InterceptSessionResult(
            case_id=case.case_id,
            label=case.label,
            humanity=case.humanity,
            engine=engine,
            ok=n_priced > 0 and err is None,
            score=score,
            items=len(items),
            priced=n_priced,
            min_price=min_p,
            api_payloads=api_payloads,
            blocked=blocked,
            page_url=page_url,
            cookies_used=cookies_used,
            error=err,
            elapsed_ms=elapsed,
        )

    def _append_log_header(self, n_cases: int) -> None:
        TEXT_LOG.parent.mkdir(parents=True, exist_ok=True)
        header = [
            "=" * 78,
            " SHOPEE network_intercept — benchmark de sessão (bot → humano)",
            f" {datetime.now().isoformat(timespec='seconds')}",
            f" query: {self.query}",
            f" casos: {n_cases}",
            f" cookies em disco: {shopee_session_ready()}",
            f" CDP online: {cdp_endpoint_alive((get_settings().shopee_cdp_url or 'http://127.0.0.1:9222').strip())}",
            "=" * 78,
            "",
        ]
        TEXT_LOG.write_text("\n".join(header), encoding="utf-8")

    def _append_case_log(
        self, result: InterceptSessionResult, case: InterceptSessionCase
    ) -> None:
        status = "SKIP" if result.skipped else ("OK" if result.ok else "FAIL")
        price = f"R$ {result.min_price:.0f}" if result.min_price else "—"
        lines = [
            f"--- {result.case_id} | humanidade {result.humanity}/10 | {status} ---",
            f"  label:    {result.label}",
            f"  engine:   {result.engine}",
            f"  score:    {result.score} | itens: {result.items} | com preço: {result.priced} | min: {price}",
            f"  api_json: {result.api_payloads} payloads | tempo: {result.elapsed_ms} ms | cookies: {result.cookies_used}",
            f"  blocked:  {result.blocked} | url: {result.page_url[:100]}",
        ]
        if case.notes:
            lines.append(f"  notas:    {case.notes}")
        if result.skip_reason:
            lines.append(f"  skip:     {result.skip_reason}")
        if result.error:
            lines.append(f"  erro:     {result.error[:200]}")
        lines.append("")
        with TEXT_LOG.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def _append_summary(self) -> None:
        ranked = sorted(self.results, key=lambda r: (-r.score, -r.humanity))
        best = next((r for r in ranked if r.ok and not r.skipped), None)
        lines = [
            "=" * 78,
            " RESUMO (ordenado por score, depois humanidade)",
            f"{'human':>5} {'score':>5} {'preço':>8} {'itens':>5} {'$':>4}  {'id':<28} engine",
            "-" * 78,
        ]
        for r in sorted(self.results, key=lambda x: x.humanity):
            if r.skipped:
                lines.append(
                    f"{r.humanity:>5} {'SKIP':>5} {'—':>8} {'—':>5} {'—':>4}  {r.case_id:<28} {r.skip_reason}"
                )
                continue
            price = f"{r.min_price:7.0f}" if r.min_price else "      —"
            lines.append(
                f"{r.humanity:>5} {r.score:>5} {price:>8} {r.items:>5} {r.priced:>4}  "
                f"{r.case_id:<28} {r.engine[:20]}"
            )
        lines.extend(
            [
                "-" * 78,
                f" Melhor sem SKIP: {best.case_id if best else 'nenhum'} — {best.label if best else ''}",
                f" JSON: {JSON_REPORT}",
                f" Debug NDJSON: debug-a309ad.log",
                "=" * 78,
                "",
            ]
        )
        with TEXT_LOG.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _save_json(self) -> None:
        JSON_REPORT.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "query": self.query,
            "strategy": "network_intercept",
            "by_humanity": [asdict(r) for r in sorted(self.results, key=lambda x: x.humanity)],
            "by_score": [asdict(r) for r in sorted(self.results, key=lambda r: (-r.score, -r.humanity))],
        }
        JSON_REPORT.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def format_table(self) -> str:
        if not TEXT_LOG.is_file():
            return "Log não gerado."
        return TEXT_LOG.read_text(encoding="utf-8")
