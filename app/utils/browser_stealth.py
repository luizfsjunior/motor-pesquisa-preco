# Sem flags “stealth” na linha de comando — Chrome 131+ marca como não suportadas.
# O script em apply_stealth() esconde navigator.webdriver.
CHROMIUM_LAUNCH_ARGS: list[str] = []


def get_chromium_launch_args(*, headless: bool, start_minimized: bool) -> list[str]:
    args = list(CHROMIUM_LAUNCH_ARGS)
    if not headless and start_minimized:
        args.append("--start-minimized")
    return args

CHROMIUM_IGNORE_DEFAULT_ARGS = [
    "--enable-automation",
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
]

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
"""

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

FIREFOX_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
    "Gecko/20100101 Firefox/133.0"
)


def should_apply_stealth(*, for_shopee: bool, cdp: bool) -> bool:
    """Shopee/CDP: sem script stealth — página deve parecer navegador normal."""
    if for_shopee or cdp:
        return False
    return True

BROWSER_LOCALE = "pt-BR"
BROWSER_TIMEZONE = "America/Sao_Paulo"
BROWSER_VIEWPORT = {"width": 1366, "height": 768}


async def apply_stealth(context) -> None:
    await context.add_init_script(STEALTH_INIT_SCRIPT)


def is_shopee_load_error_html(html: str) -> bool:
    lower = html.lower()
    return (
        "erro de carregamento" in lower
        or "problemas ao carregar" in lower
        or "try again" in lower and "loading" in lower
    )


def is_shopee_blocked_html(html: str) -> bool:
    lower = html.lower()
    return (
        is_shopee_load_error_html(html)
        or "captcha" in lower
        or "verify/traffic" in lower
        or "are you a robot" in lower
        or "unusual traffic" in lower
    )
