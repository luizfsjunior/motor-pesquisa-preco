import re

from app.config.loader import ProductRelevanceConfig
from app.normalization.title import _remove_accents, should_ignore_title


def _norm(title: str) -> str:
    return _remove_accents(title.lower())


def is_relevant_product(
    title: str,
    relevance: ProductRelevanceConfig,
    *,
    price: float | None = None,
) -> bool:
    """Mantém anúncios de console Switch 2; exclui jogos, Lite, gen.1 e peças."""
    lower = _norm(title)

    if not any(term in lower for term in relevance.must_contain_any):
        return False

    if should_ignore_title(title, relevance.exclude_terms):
        return False

    if re.search(r"switch\s+oled", lower) and not re.search(
        r"switch\s*2|switch\s*ii", lower
    ):
        return False

    if re.search(r"switch\s+32", lower) and not re.search(
        r"switch\s*2|switch\s*ii", lower
    ):
        return False

    if "switch lite" in lower or re.search(r"\blite\b", lower):
        return False

    if re.search(r"\(digital\)|\bdigital\b|\+\s*dlc|dlc\)", lower):
        if not _has_strong_console_keyword(lower, relevance.console_keywords):
            return False

    if re.search(r"switch\s*2\s+edition", lower) and not _has_strong_console_keyword(
        lower, relevance.console_keywords
    ):
        return False

    if _looks_like_game_not_console(lower, relevance):
        return False

    if price is not None and price < relevance.min_console_price:
        if not _has_strong_console_keyword(lower, relevance.console_keywords):
            return False

    return True


def _has_strong_console_keyword(lower: str, keywords: list[str]) -> bool:
    return any(kw in lower for kw in keywords)


def _looks_like_game_not_console(
    lower: str, relevance: ProductRelevanceConfig
) -> bool:
    has_game_marker = any(m in lower for m in relevance.game_markers)
    if not has_game_marker:
        return False
    return not _has_strong_console_keyword(lower, relevance.console_keywords)
