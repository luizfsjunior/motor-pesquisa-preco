import re

# Texto no card de busca do ML que indica compra internacional / importação
ML_INTERNATIONAL_MARKERS = (
    "compra internacional",
    "internacional",
    "envio do exterior",
    "envio internacional",
    "envio da china",
    "envio dos eua",
    "importação",
    "importado",
    "full import",
    "versão americana",
    "versao americana",
    "version americana",
    "global selling",
)

FOREIGN_ML_HOSTS = (
    ".com.ar",
    ".com.mx",
    ".com.co",
    ".cl/",
    "mercadolibre.com",
    "mercadolibre.com.ar",
    "mercadolibre.com.mx",
)


def is_brazil_ml_href(href: str) -> bool:
    if not href:
        return False
    lower = href.lower()
    if any(host in lower for host in FOREIGN_ML_HOSTS):
        return False
    if "mercadolivre.com" in lower and "mercadolivre.com.br" not in lower:
        return False
    return bool(re.search(r"\bMLB\d+", href, re.IGNORECASE))


def card_text_suggests_international(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in ML_INTERNATIONAL_MARKERS)
