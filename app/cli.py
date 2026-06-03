import asyncio

import typer

from app.database.session import init_db
from app.config.loader import load_app_config
from app.config.settings import get_settings
from app.scrapers.shopee import ShopeeScraper
from app.services.monitor import PriceMonitorService
from app.utils.playwright import PlaywrightManager
from app.utils.export import export_csv, export_excel
from app.utils.logging_setup import setup_logging
from pathlib import Path

from app.utils.shopee_auth import (
    import_storage_state_file,
    print_manual_cookie_instructions,
    save_shopee_session,
    shopee_session_ready,
    shopee_storage_path,
)

app = typer.Typer(help="Motor de pesquisa de preços multi-marketplace")


@app.command("init-db")
def init_db_cmd() -> None:
    """Cria tabelas no SQLite."""
    setup_logging()
    init_db()
    typer.echo("Database initialized.")


@app.command("run-once")
def run_once() -> None:
    """Executa um ciclo completo de scraping."""
    setup_logging()
    init_db()
    service = PriceMonitorService()
    stats = asyncio.run(service.run_cycle())
    typer.echo(f"Cycle done: {stats}")
    if stats.get("digest_sent"):
        typer.echo("Telegram: fallback digest (menor preço ou aviso sem dados) enviado.")
    elif stats.get("alerts"):
        typer.echo("Telegram: alerta(s) de promoção enviado(s).")


@app.command("shopee-login")
def shopee_login_cmd(
    chrome_profile: bool = typer.Option(
        False,
        "--chrome-profile",
        help="Usa seu Google Chrome já logado (feche o Chrome antes).",
    ),
) -> None:
    """Abre o navegador para login na Shopee e salva a sessão (cookies)."""
    setup_logging()
    path = asyncio.run(save_shopee_session(use_chrome_profile=chrome_profile))
    typer.echo(f"Sessão Shopee salva em {path}")
    typer.echo("Agora pode rodar: python -m app.cli run-once")


@app.command("deploy-check")
def deploy_check_cmd() -> None:
    """Verifica CDP, Telegram e modo Shopee (VPS/local)."""
    from app.utils.playwright import cdp_endpoint_alive
    from app.utils.shopee_auth import shopee_session_ready

    settings = get_settings()
    cdp = (settings.shopee_cdp_url or "").strip()
    typer.echo("=== Deploy check ===")
    typer.echo(f"Telegram: {'OK' if settings.telegram_enabled else 'OFF'}")
    typer.echo(f"Cookies:  {'OK' if shopee_session_ready() else 'ausente'}")
    typer.echo(f"SHOPEE_FALLBACK_ONLY: {settings.shopee_fallback_only}")
    if settings.shopee_fallback_only:
        typer.echo("Shopee: plano B (DuckDuckGo/Bing/Google)")
    elif cdp:
        if cdp_endpoint_alive(cdp):
            typer.echo(f"CDP: OK ({cdp})")
        else:
            typer.echo(f"CDP: OFFLINE ({cdp})")
            if not settings.shopee_cdp_strict:
                typer.echo("  -> fallback DDG ativo quando CDP falhar")
    else:
        typer.echo("CDP: nao configurado")


@app.command("shopee-cdp-check")
def shopee_cdp_check_cmd() -> None:
    """Verifica se o Chrome está ouvindo na porta CDP (9222)."""
    from app.utils.playwright import cdp_endpoint_alive

    settings = get_settings()
    cdp = (settings.shopee_cdp_url or "http://127.0.0.1:9222").strip()
    if cdp_endpoint_alive(cdp):
        typer.echo(f"OK — Chrome CDP ativo em {cdp}")
    else:
        typer.echo(f"OFFLINE — rode: scripts\\start-chrome-cdp.bat")
        typer.echo("Depois faça login em shopee.com.br nessa janela do Chrome.")
        raise typer.Exit(code=1)


@app.command("shopee-cdp-help")
def shopee_cdp_help_cmd() -> None:
    """Como usar seu Chrome real (logado na Shopee) para capturar preços."""
    print(
        """
=== Shopee com preço: Chrome real via CDP (recomendado) ===

1. No .env: SHOPEE_CDP_URL=http://127.0.0.1:9222

2. Duplo-clique ou rode no terminal:
   scripts\\start-chrome-cdp.bat
   (abre Chrome com perfil em data\\chrome_cdp_profile — não use o Chrome normal ao mesmo tempo)

3. Na janela que abrir: login em https://shopee.com.br/buyer/login
   NAO clique em "Continuar com Google" — o Google retorna erro 400
   neste Chrome de depuracao. Use e-mail ou telefone + SMS da Shopee.

4. Verifique:
   python -m app.cli shopee-cdp-check

5. Teste preço em um produto:
   python -m app.cli shopee-test-product "URL-shopee-i.loja.item"

6. Ciclo: python -m app.cli run-once

Navegador ( .env SHOPEE_BROWSER ): firefox | brave | chrome | chromium
Com captcha: SHOPEE_INTERACTIVE=true + HEADLESS=false — resolva na janela e ENTER.

CDP (Chrome logado): scripts/start-chrome-cdp.bat + SHOPEE_CDP_URL (sem Google login).
        """.strip()
    )


@app.command("shopee-test-product")
def shopee_test_product_cmd(
    url: str = typer.Argument(..., help="URL Shopee -i.loja.item"),
) -> None:
    """Testa extração de preço em uma página de produto (get_pc + HTML)."""
    setup_logging()
    config = load_app_config()
    pw = PlaywrightManager(for_shopee=True)

    async def _run() -> None:
        scraper = ShopeeScraper(config, pw)
        try:
            item = await scraper._scrape_product_url(url)
            if item:
                typer.echo(f"OK R$ {item.current_price:.2f} | {item.title[:80]}")
                typer.echo(item.url)
            else:
                typer.echo("Falhou — captcha ou API bloqueada. Tente shopee-cdp-help.")
                raise typer.Exit(code=1)
        finally:
            await scraper.close()

    asyncio.run(_run())


@app.command("shopee-help")
def shopee_help_cmd() -> None:
    """Instruções quando Shopee mostra erro de carregamento ou captcha."""
    print_manual_cookie_instructions()


@app.command("shopee-import-state")
def shopee_import_state_cmd(
    source: Path = typer.Argument(..., help="Arquivo JSON storage_state do Playwright"),
) -> None:
    """Importa sessão Shopee exportada manualmente (formato Playwright)."""
    setup_logging()
    path = import_storage_state_file(source)
    typer.echo(f"Sessão importada para {path}")


@app.command("shopee-test")
def shopee_test_cmd(
    query: str = typer.Option("Nintendo Switch 2", "--query", "-q"),
) -> None:
    """Testa todas as estratégias Shopee em sequência (ordem do YAML)."""
    setup_logging()
    config = load_app_config()
    pw = PlaywrightManager(for_shopee=True)

    async def _run() -> None:
        scraper = ShopeeScraper(config, pw)
        try:
            items = await scraper.search_products(query)
            typer.echo(f"Shopee test: {len(items)} itens para '{query}'")
            for p in items[:8]:
                price = (
                    f"R$ {p.current_price:.2f}"
                    if p.current_price > 0
                    else "(sem preço)"
                )
                typer.echo(f"  {price} | {p.title[:70]}")
        finally:
            await scraper.close()

    asyncio.run(_run())


@app.command("shopee-test-firefox")
def shopee_test_firefox_cmd(
    query: str = typer.Option("Nintendo Switch 2", "--query", "-q"),
    with_cdp: bool = typer.Option(
        False,
        "--with-cdp",
        help="Roda também CDP para comparar (precisa Chrome na porta 9222)",
    ),
) -> None:
    """Testa network_intercept no Firefox (visível + headless) vs opcional CDP."""
    from datetime import datetime
    from pathlib import Path

    from app.config.settings import PROJECT_ROOT, get_settings
    from app.scrapers.shopee import ShopeeScraper
    from app.utils.debug_agent_log import agent_log
    from app.utils.playwright import PlaywrightManager, cdp_endpoint_alive
    from app.utils.playwright_browsers import firefox_playwright_installed
    from app.utils.shopee_auth import shopee_session_ready

    log_path = PROJECT_ROOT / "data" / "shopee_firefox_test.log"

    setup_logging()
    config = load_app_config()

    if not firefox_playwright_installed():
        typer.echo("Firefox Playwright NAO instalado. Rode:")
        typer.echo("  playwright install firefox")
        raise typer.Exit(1)

    async def _run_one(label: str, **pw_kw) -> dict:
        pw = PlaywrightManager(for_shopee=True, skip_cdp=True, **pw_kw)
        scraper = ShopeeScraper(config, pw)
        try:
            await pw.start()
            items = await scraper._search_via_network_intercept(query)
            meta = dict(scraper._last_intercept_meta or {})
            priced = [i for i in items if i.current_price > 0]
            return {
                "label": label,
                "engine": pw.engine_label,
                "items": len(items),
                "priced": len(priced),
                "min_price": min((p.current_price for p in priced), default=None),
                "meta": meta,
                "error": None,
            }
        except Exception as exc:
            return {
                "label": label,
                "engine": pw.engine_label,
                "items": 0,
                "priced": 0,
                "min_price": None,
                "meta": {},
                "error": str(exc)[:300],
            }
        finally:
            await scraper.close()

    async def _run() -> None:
        lines = [
            "=" * 72,
            " SHOPEE Firefox test — network_intercept",
            f" {datetime.now().isoformat(timespec='seconds')}",
            f" query: {query}",
            f" cookies: {shopee_session_ready()}",
            "=" * 72,
            "",
        ]
        cases = [
            ("Firefox visivel + cookies", {"browser_override": "firefox", "headless_override": False}),
            ("Firefox headless + cookies", {"browser_override": "firefox", "headless_override": True}),
        ]
        if with_cdp:
            cases.append(
                ("CDP Chrome (referencia)", {"browser_override": "chrome", "force_cdp": True, "skip_cdp": False}),
            )
        for label, kw in cases:
            if label.startswith("CDP") and not cdp_endpoint_alive(
                (get_settings().shopee_cdp_url or "http://127.0.0.1:9222").strip()
            ):
                lines.append(f"--- {label} --- SKIP (CDP offline)")
                continue
            typer.echo(f"Testando: {label}...")
            r = await _run_one(label, **kw)
            agent_log(
                "cli.shopee_test_firefox",
                "firefox_test_result",
                r,
                "FF",
                run_id="firefox-test",
            )
            lines.append(f"--- {r['label']} ---")
            lines.append(f"  engine:   {r['engine']}")
            lines.append(f"  itens:    {r['items']} | com preco: {r['priced']}")
            if r["min_price"]:
                lines.append(f"  min:      R$ {r['min_price']:.2f}")
            if r.get("meta"):
                lines.append(f"  payloads: {r['meta'].get('api_payloads', 0)}")
                lines.append(f"  blocked:  {r['meta'].get('blocked')}")
                lines.append(f"  url:      {str(r['meta'].get('page_url', ''))[:100]}")
            if r["error"]:
                lines.append(f"  erro:     {r['error']}")
            lines.append("")
            typer.echo(
                f"  -> {r['priced']} com preco / {r['items']} total | engine={r['engine']}"
            )

        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n".join(lines), encoding="utf-8")
        typer.echo(f"\nLog salvo: {log_path}")
        typer.echo("NDJSON: debug-a309ad.log")

    asyncio.run(_run())


@app.command("shopee-benchmark-intercept")
def shopee_benchmark_intercept_cmd(
    query: str = typer.Option("Nintendo Switch 2", "--query", "-q"),
) -> None:
    """Benchmark network_intercept: sessão bot (1/10) → humano/CDP (10/10)."""
    from app.services.shopee_intercept_benchmark import ShopeeInterceptBenchmarkRunner

    setup_logging()
    config = load_app_config()

    async def _run() -> None:
        runner = ShopeeInterceptBenchmarkRunner(config, query=query)
        await runner.run_all()
        typer.echo(runner.format_table())
        typer.echo(
            "\nArquivos: data/shopee_intercept_benchmark.log e .json | debug-a309ad.log"
        )

    asyncio.run(_run())


@app.command("shopee-benchmark")
def shopee_benchmark_cmd(
    query: str = typer.Option("Nintendo Switch 2", "--query", "-q"),
    product_url: str = typer.Option(
        "",
        "--product-url",
        "-u",
        help="URL de produto Shopee (-i.loja.item); vazio = padrão Switch 2",
    ),
    include_interactive: bool = typer.Option(
        False,
        "--include-interactive",
        help="Inclui teste que pausa para você resolver captcha (ENTER)",
    ),
    quick: bool = typer.Option(
        False,
        "--quick",
        help="Só tiers 1–10 (produto + DDG; ~10 min). Sem --quick roda os 19–20 testes.",
    ),
) -> None:
    """Testa ~20 opções Shopee (CDP, Firefox, Brave, Chrome, DDG…) e ranqueia."""
    from app.services.shopee_benchmark import (
        DEFAULT_PRODUCT_URL,
        ShopeeBenchmarkRunner,
    )

    setup_logging()
    config = load_app_config()
    url = product_url.strip() or DEFAULT_PRODUCT_URL

    async def _run() -> None:
        runner = ShopeeBenchmarkRunner(
            config,
            product_url=url,
            query=query,
            include_interactive=include_interactive,
            quick=quick,
        )
        results = await runner.run_all()
        typer.echo(runner.format_table())
        winners = [r for r in results if r.ok and not r.skipped]
        if winners:
            w = winners[0]
            typer.echo(
                f"Melhor opção agora: {w.case_id} — {w.label} "
                f"(score={w.score}, min=R$ {w.min_price:.0f})"
            )
        else:
            typer.echo(
                "Nenhuma opção retornou preço. Tente: scripts\\start-chrome-cdp.bat "
                "+ login Shopee (e-mail, não Google) ou --include-interactive"
            )

    asyncio.run(_run())


@app.command("shopee-test-strategies")
def shopee_test_strategies_cmd(
    query: str = typer.Option("Nintendo Switch 2", "--query", "-q"),
) -> None:
    """Testa cada estratégia Shopee isoladamente e grava resultado no log debug."""
    setup_logging()
    config = load_app_config()
    pw = PlaywrightManager(for_shopee=True)

    async def _run() -> None:
        from app.utils.debug_agent_log import agent_log

        scraper = ShopeeScraper(config, pw)
        typer.echo(f"Testando estratégias Shopee para '{query}'...\n")
        try:
            for name, fn in scraper._build_strategies():
                try:
                    items = await fn(query)
                    priced = sum(1 for i in items if i.current_price > 0)
                    typer.echo(
                        f"  {name:22} -> {len(items):3} itens ({priced} com preço)"
                    )
                    agent_log(
                        "cli.shopee_test_strategies",
                        "strategy_result",
                        {
                            "strategy": name,
                            "count": len(items),
                            "priced": priced,
                            "query": query,
                        },
                        "H8",
                        run_id="strategies",
                    )
                    for p in items[:3]:
                        typer.echo(f"      - {p.title[:55]}")
                except Exception as exc:
                    typer.echo(f"  {name:22} -> ERRO: {exc}")
                    agent_log(
                        "cli.shopee_test_strategies",
                        "strategy_error",
                        {"strategy": name, "error": str(exc)[:200]},
                        "H8",
                        run_id="strategies",
                    )
        finally:
            await scraper.close()
        typer.echo("\nVer também: debug-a309ad.log")

    asyncio.run(_run())


@app.command("shopee-session")
def shopee_session_cmd() -> None:
    """Verifica se o arquivo de sessão da Shopee existe."""
    path = shopee_storage_path()
    if shopee_session_ready():
        typer.echo(f"OK — sessão Shopee encontrada: {path}")
    else:
        typer.echo(f"Ausente — rode: python -m app.cli shopee-login")
        raise typer.Exit(code=1)


@app.command("export-csv")
def export_csv_cmd() -> None:
    path = export_csv()
    typer.echo(f"CSV exported to {path}")


@app.command("export-excel")
def export_excel_cmd() -> None:
    path = export_excel()
    typer.echo(f"Excel exported to {path}")


if __name__ == "__main__":
    app()
