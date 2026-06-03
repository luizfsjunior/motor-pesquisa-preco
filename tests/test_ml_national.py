from app.scrapers.ml_national import (
    card_text_suggests_international,
    is_brazil_ml_href,
)


def test_ml_national_href_and_text() -> None:
    assert is_brazil_ml_href(
        "https://www.mercadolivre.com.br/nintendo-switch-2/p/MLB2026260042"
    )
    assert not is_brazil_ml_href("https://articulo.mercadolibre.com.ar/MLA123")
    assert card_text_suggests_international("Compra internacional Envio do exterior")
    assert not card_text_suggests_international("Frete grátis Envio nacional")
