import re
import unicodedata

from app.config.loader import ProductConfig


def _remove_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def should_ignore_title(title: str, ignored_terms: list[str]) -> bool:
    lower = title.lower()
    return any(term.lower() in lower for term in ignored_terms)


def normalize_title(title: str, product_config: ProductConfig) -> str:
    text = _remove_accents(title.lower())
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for rule in product_config.normalization_rules:
        if len(rule) >= 2:
            src, dst = rule[0].lower(), rule[1]
            text = text.replace(src.lower(), dst.lower())
    text = re.sub(r"\s+", " ", text).strip()
    tokens = sorted(text.split())
    return " ".join(tokens)
