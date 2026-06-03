import json
import time
from pathlib import Path
from typing import Any

_DEBUG_LOG = Path(__file__).resolve().parents[2] / "debug-a309ad.log"
_SESSION = "a309ad"


def agent_log(
    location: str,
    message: str,
    data: dict[str, Any],
    hypothesis_id: str,
    *,
    run_id: str = "pre-fix",
) -> None:
    # region agent log
    payload = {
        "sessionId": _SESSION,
        "timestamp": int(time.time() * 1000),
        "location": location,
        "message": message,
        "data": data,
        "hypothesisId": hypothesis_id,
        "runId": run_id,
    }
    with _DEBUG_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    # endregion


async def log_page_scrape_diagnostic(
    page: Any,
    *,
    marketplace: str,
    query: str,
    items_parsed: int,
    extra: dict[str, Any] | None = None,
) -> None:
    """Diagnóstico quando scrape retorna pouco/nada (H4/H5/H6)."""
    # region agent log
    try:
        title = await page.title()
        url = page.url
        content = await page.content()
        lower = content.lower()
        counts = {
            "ml_layout_item": await page.locator(
                "li.ui-search-layout__item, div.ui-search-layout__item"
            ).count(),
            "shopee_cards": await page.locator(
                "div[class*='shopee-search-item-result'] a, li.shopee-search-item-result__item a"
            ).count(),
            "google_cards": await page.locator(
                "div[data-docid], li[data-oid], div.sh-dgr__grid-result, div.sh-dgr__content"
            ).count(),
            "any_product_link": await page.locator("a[href*='produto'], a[href*='MLB']").count(),
        }
        data: dict[str, Any] = {
            "marketplace": marketplace,
            "query": query,
            "items_parsed": items_parsed,
            "page_title": (title or "")[:120],
            "page_url": (url or "")[:220],
            "html_len": len(content),
            "has_captcha": "captcha" in lower or "unusual traffic" in lower,
            "has_robot": "robot" in lower or "automated" in lower,
            "selector_counts": counts,
        }
        if extra:
            data.update(extra)
        agent_log(
            "debug_agent_log.log_page_scrape_diagnostic",
            "scrape_page_diagnostic",
            data,
            "H5",
        )
    except Exception as exc:
        agent_log(
            "debug_agent_log.log_page_scrape_diagnostic",
            "scrape_page_diagnostic_error",
            {"marketplace": marketplace, "query": query, "error": str(exc)},
            "H5",
        )
    # endregion
