"""Detecção de navegadores Playwright instalados."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from loguru import logger

EXTERNAL_SEARCH_STRATEGIES = frozenset(
    {"duckduckgo_site", "bing_site", "google_site"}
)


def _firefox_path_from_dry_run() -> Path | None:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "firefox"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        for line in (proc.stdout + proc.stderr).splitlines():
            if "install location" in line.lower() and "firefox" in line.lower():
                raw = line.split(":", 1)[-1].strip()
                if raw:
                    return Path(raw)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def firefox_playwright_installed() -> bool:
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if base.is_dir():
        for folder in base.glob("firefox-*"):
            exe = folder / "firefox" / "firefox.exe"
            if exe.is_file():
                return True
    dry = _firefox_path_from_dry_run()
    if dry is not None:
        exe = dry / "firefox" / "firefox.exe"
        if exe.is_file():
            return True
        if dry.is_dir() and any(dry.glob("**/firefox.exe")):
            return True
    return False


def resolve_shopee_browser(requested: str | None) -> str:
    """Retorna o navegador a usar; faz fallback para Chrome se Firefox não existir."""
    browser = (requested or "chrome").lower().strip()
    if browser != "firefox":
        return browser
    if firefox_playwright_installed():
        return "firefox"
    logger.warning(
        "Firefox do Playwright não está instalado. "
        "Rode: playwright install firefox — usando Chrome por enquanto."
    )
    return "chrome"
