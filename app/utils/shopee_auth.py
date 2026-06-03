import asyncio
import json
import os
import shutil
from pathlib import Path

from loguru import logger
from playwright.async_api import BrowserContext, async_playwright

from app.config.settings import PROJECT_ROOT, get_settings
from app.utils.browser_stealth import (
    BROWSER_LOCALE,
    BROWSER_TIMEZONE,
    BROWSER_VIEWPORT,
    CHROMIUM_IGNORE_DEFAULT_ARGS,
    DEFAULT_USER_AGENT,
    apply_stealth,
    get_chromium_launch_args,
    is_shopee_blocked_html,
)


def shopee_storage_path() -> Path:
    settings = get_settings()
    path = Path(settings.shopee_storage_state_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def shopee_profile_dir() -> Path:
    return PROJECT_ROOT / "data" / "shopee_browser_profile"


def shopee_session_ready() -> bool:
    return shopee_storage_path().is_file()


def default_chrome_user_data_dir() -> Path | None:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    path = Path(local) / "Google" / "Chrome" / "User Data"
    return path if path.is_dir() else None


def import_storage_state_file(source: Path) -> Path:
    """Copia JSON exportado (formato Playwright storage_state) para data/."""
    target = shopee_storage_path()
    if not source.is_file():
        raise FileNotFoundError(f"Arquivo não encontrado: {source}")
    data = json.loads(source.read_text(encoding="utf-8"))
    if "cookies" not in data:
        raise ValueError(
            "JSON inválido: precisa do formato Playwright storage_state "
            '(chave "cookies"). Veja README seção Shopee.'
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    logger.info("Sessão Shopee importada de {} para {}", source, target)
    return target


def print_manual_cookie_instructions() -> None:
    print(
        """
=== Shopee: login manual (sem automação) ===

A Shopee costuma bloquear navegador automatizado (erro de carregamento / captcha).

Login CDP (Chrome scripts/start-chrome-cdp.bat):
  Use e-mail/telefone na Shopee. "Continuar com Google" da erro 400 — nao use.

Opção A — Perfil isolado (melhor para run-once automático):
  1. Rode: python -m app.cli shopee-login
  2. Login/captcha na janela → ENTER
  3. No .env: SHOPEE_PERSISTENT_PROFILE=true e HEADLESS=false

Opção B — Perfil do seu Chrome (só exporta cookies):
  1. Feche TODO o Google Chrome
  2. Rode: python -m app.cli shopee-login --chrome-profile
  3. Pressione ENTER com shopee.com.br ok

Opção C — Importar sessão Playwright:
  1. No Chrome normal, faça login em https://shopee.com.br
  2. Instale extensão "Cookie-Editor" (Chrome Web Store)
  3. Exporte cookies para JSON e converta para storage_state
     (ou use Playwright: npx playwright codegen shopee.com.br --save-storage=data/shopee_storage_state.json)
  4. Rode: python -m app.cli shopee-import-state CAMINHO.json

Opção D — URLs fixas (sem busca):
  Em config/products.yaml → marketplaces.shopee_options.watch_urls:
  cole links de produto (-i.loja.item) copiados do celular/navegador normal.

Opção E — Só Mercado Livre:
  Em config/products.yaml defina: marketplaces.shopee: false

Depois: python -m app.cli shopee-session
        """.strip()
    )


async def _launch_login_context(playwright, *, use_chrome_profile: bool) -> BrowserContext:
    settings = get_settings()
    minimized_args = get_chromium_launch_args(
        headless=False,
        start_minimized=settings.browser_start_minimized,
    )
    if use_chrome_profile:
        chrome_data = default_chrome_user_data_dir()
        if not chrome_data:
            raise RuntimeError("Perfil do Chrome não encontrado (LOCALAPPDATA).")
        print(
            "\n>>> Usando seu perfil do Chrome. O Chrome deve estar FECHADO antes de continuar.\n"
        )
        user_data = str(chrome_data)
        extra_args = [*minimized_args, "--profile-directory=Default"]
    else:
        profile = shopee_profile_dir()
        profile.mkdir(parents=True, exist_ok=True)
        user_data = str(profile)
        extra_args = minimized_args

    common = {
        "user_data_dir": user_data,
        "headless": False,
        "locale": BROWSER_LOCALE,
        "timezone_id": BROWSER_TIMEZONE,
        "viewport": BROWSER_VIEWPORT,
        "args": extra_args,
        "ignore_default_args": CHROMIUM_IGNORE_DEFAULT_ARGS,
        "user_agent": DEFAULT_USER_AGENT,
    }
    for channel in ("chrome", "msedge", None):
        try:
            kwargs = dict(common)
            if channel:
                kwargs["channel"] = channel
            ctx = await playwright.chromium.launch_persistent_context(**kwargs)
            await apply_stealth(ctx)
            logger.info(
                "Navegador Shopee: {} ({})",
                "perfil Chrome do usuário" if use_chrome_profile else "perfil isolado",
                channel or "bundled",
            )
            return ctx
        except Exception as exc:
            logger.debug("Canal {} indisponível: {}", channel or "bundled", exc)
    raise RuntimeError(
        "Não foi possível abrir o navegador. Feche o Chrome e tente "
        "python -m app.cli shopee-login --chrome-profile"
    )


async def save_shopee_session(*, use_chrome_profile: bool = False) -> Path:
    target = shopee_storage_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        context = await _launch_login_context(p, use_chrome_profile=use_chrome_profile)
        page = context.pages[0] if context.pages else await context.new_page()
        logger.info("Abrindo https://shopee.com.br/ (aguarde carregar)…")
        await page.goto("https://shopee.com.br/", wait_until="domcontentloaded", timeout=90000)
        _print_page_hints(await page.content())

        print("\n>>> Faça login / resolva captcha na janela do navegador.")
        print(">>> Quando shopee.com.br estiver normal, pressione ENTER aqui.\n")
        await asyncio.to_thread(input)

        await page.goto("https://shopee.com.br/", wait_until="domcontentloaded", timeout=90000)
        html_after = await page.content()
        if is_shopee_blocked_html(html_after):
            logger.warning("Página ainda com bloqueio — salvando cookies mesmo assim")
            print(
                ">>> Aviso: página ainda parece bloqueada, mas vamos salvar os cookies.\n"
                ">>> Se run-once falhar, use shopee-import-state ou desative shopee no YAML.\n"
            )
        await context.storage_state(path=str(target))
        try:
            await context.close()
        except Exception as exc:
            logger.debug("Context close: {}", exc)

    logger.info("Sessão Shopee salva em {}", target)
    return target


def _print_page_hints(html: str) -> None:
    if is_shopee_blocked_html(html):
        print(
            "\n>>> Shopee: erro de carregamento / possível captcha detectado.\n"
            ">>> Resolva na janela (Tentar novamente, login, captcha).\n"
            ">>> Se não funcionar: python -m app.cli shopee-help\n"
        )
