"""Extração de preço Shopee a partir de API get_pc ou JSON embutido no HTML."""

import json
import re
from typing import Any

SHOPEE_PDP_API = re.compile(r"/api/v4/pdp/get_pc")
PRICE_JSON_RE = re.compile(
    r'"(?:price|price_min|price_before_discount)"\s*:\s*(\d{4,})',
    re.IGNORECASE,
)


def shopee_raw_to_brl(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value > 100_000:
        return value / 100_000
    return value


def _dig_item(node: dict) -> dict | None:
    if not isinstance(node, dict):
        return None
    data = node.get("data")
    if isinstance(data, dict):
        item = data.get("item") or data.get("item_basic")
        if isinstance(item, dict):
            return item
        if any(k in data for k in ("price", "price_min", "name")):
            return data
    item = node.get("item") or node.get("item_basic")
    if isinstance(item, dict):
        return item
    if any(k in node for k in ("price", "price_min", "name")):
        return node
    return None


def parse_get_pc_payload(payload: dict) -> dict[str, Any] | None:
    if payload.get("error"):
        return None
    item = _dig_item(payload)
    if not item:
        return None
    price = shopee_raw_to_brl(
        item.get("price")
        or item.get("price_min")
        or item.get("single_price")
    )
    if not price:
        return None
    title = (item.get("name") or item.get("title") or "").strip()
    original = shopee_raw_to_brl(item.get("price_before_discount") or item.get("price_max"))
    return {
        "title": title,
        "current_price": price,
        "original_price": original,
        "image": item.get("image"),
    }


def parse_get_pc_payloads(payloads: list[dict]) -> dict[str, Any] | None:
    for payload in payloads:
        parsed = parse_get_pc_payload(payload)
        if parsed:
            return parsed
    return None


def parse_price_from_html(html: str) -> dict[str, Any] | None:
    lower = html.lower()
    if "captcha" in lower and "verify/traffic" in lower:
        return None
    for script_m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        try:
            ld = json.loads(script_m.group(1))
        except json.JSONDecodeError:
            continue
        nodes = ld if isinstance(ld, list) else [ld]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            offers = node.get("offers")
            if isinstance(offers, dict):
                price = offers.get("price") or offers.get("lowPrice")
                p = shopee_raw_to_brl(price)
                if p:
                    name = (node.get("name") or "").strip()
                    return {"title": name, "current_price": p, "original_price": None}
    prices: list[float] = []
    for m in PRICE_JSON_RE.finditer(html):
        p = shopee_raw_to_brl(m.group(1))
        if p and 500 <= p <= 50_000:
            prices.append(p)
    if not prices:
        return None
    return {
        "title": "",
        "current_price": min(prices),
        "original_price": None,
    }


def build_get_pc_url(shop_id: str, item_id: str) -> str:
    return (
        f"https://shopee.com.br/api/v4/pdp/get_pc"
        f"?item_id={item_id}&shop_id={shop_id}"
    )
