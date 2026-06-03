from app.config.loader import load_app_config
from app.normalization.relevance import is_relevant_product


def test_relevance_switch2_console_only() -> None:
    rel = load_app_config().product.relevance
    assert is_relevant_product("Consola Nintendo Switch 2 256gb Nacional", rel)
    assert not is_relevant_product(
        "Consola Nintendo Switch 2 256gb Version Americana", rel
    )
    assert not is_relevant_product("Nintendo Switch Lite Turquesa", rel)
    assert not is_relevant_product("Jogo Mario Kart World Switch 2 Nintendo", rel)
    assert not is_relevant_product(
        "Nintendo Switch Oled Model - The Legend Of Zelda: Tears O", rel
    )
    assert not is_relevant_product("Ci Bq24193 Carga Reparo P/ Nintendo Switch Lite", rel)
    assert not is_relevant_product(
        "Yoshi And The Mysterious Book Nintendo Switch 2 Edition", rel
    )
    assert not is_relevant_product(
        "Donkey Kong Bananza Bundle (Game + DLC) Nintendo Switch 2 (Digital)",
        rel,
        price=499.0,
    )
    assert not is_relevant_product(
        "Virtual Boy Para Nintendo Switch 2/ Nintendo Switch Lacrado",
        rel,
        price=3139.0,
    )
