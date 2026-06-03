from app.config.loader import AppConfig
from app.models.schemas import ScrapedProduct, TrustLevel, TrustResult

SUSPICIOUS_TERMS = [
    "replica",
    "réplica",
    "fake",
    "clone",
    "importado sem garantia",
    "sem nota",
    "usado",
    "defeito",
    "peça",
]


def calculate_trust_score(product: ScrapedProduct, config: AppConfig) -> TrustResult:
    score = 100
    reasons: list[str] = []
    price = product.total_price
    pr = config.product.expected_price_range
    min_expected = pr.min
    max_expected = pr.max
    factor = config.product.suspicious_price_factor

    if price < min_expected * factor:
        score -= 40
        reasons.append(f"Preço muito abaixo do esperado (< {min_expected * factor:.0f})")
    elif price < min_expected:
        score -= 20
        reasons.append("Preço abaixo da faixa esperada")
    elif price > max_expected:
        score -= 15
        reasons.append("Preço acima da faixa esperada")

    if product.rating is not None:
        if product.rating < config.filters.minimum_store_rating:
            score -= 25
            reasons.append(f"Avaliação baixa ({product.rating})")
    else:
        score -= 10
        reasons.append("Sem avaliação da loja")

    if product.sold_count is not None:
        if product.sold_count < config.filters.minimum_store_sales:
            score -= 20
            reasons.append(f"Poucas vendas ({product.sold_count})")
    else:
        score -= 8
        reasons.append("Vendas não informadas")

    if not product.store_name or len(product.store_name.strip()) < 2:
        score -= 15
        reasons.append("Loja não identificada")

    if len(product.title) < 15:
        score -= 10
        reasons.append("Título muito curto")

    lower_title = product.title.lower()
    for term in SUSPICIOUS_TERMS:
        if term in lower_title:
            score -= 15
            reasons.append(f"Termo suspeito: {term}")
            break

    score = max(0, min(100, score))
    if score >= 70:
        level = TrustLevel.HIGH
    elif score >= 45:
        level = TrustLevel.MEDIUM
    else:
        level = TrustLevel.LOW

    rejected = score < config.trust.minimum_score_to_persist
    return TrustResult(score=score, level=level, reasons=reasons, rejected=rejected)
