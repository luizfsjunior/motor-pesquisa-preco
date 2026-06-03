from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.config.settings import PROJECT_ROOT, Settings, get_settings

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "products.yaml"


class PriceRangeConfig(BaseModel):
    min: float
    max: float


class ProductRelevanceConfig(BaseModel):
    """Filtro de anúncios: foco em console Nintendo Switch 2."""

    must_contain_any: list[str] = Field(
        default_factory=lambda: ["switch 2", "switch ii"]
    )
    exclude_terms: list[str] = Field(default_factory=list)
    console_keywords: list[str] = Field(
        default_factory=lambda: [
            "console",
            "consola",
            "system",
            "nova geracao",
            "nova geração",
            "256gb",
            "256 gb",
        ]
    )
    min_console_price: float = Field(
        default=2000.0,
        description="Abaixo deste preço exige palavra-chave forte de console (evita jogos).",
    )
    game_markers: list[str] = Field(
        default_factory=lambda: [
            "jogo",
            "game",
            "midia fisica",
            "mídia física",
            "midia física",
            "digital)",
            "(digital",
            "limited run",
            "video game",
        ]
    )


class ProductConfig(BaseModel):
    main_term: str
    search_terms: list[str]
    ignored_terms: list[str]
    normalization_rules: list[list[str]]
    expected_price_range: PriceRangeConfig
    suspicious_price_factor: float = 0.55
    relevance: ProductRelevanceConfig = Field(default_factory=ProductRelevanceConfig)


class ShopeeOptionsConfig(BaseModel):
    """Alternativas quando API direta retorna 403 / captcha."""

    prefer_external_search_first: bool = False
    skip_out_of_stock: bool = True
    use_clean_browser_for_external: bool = True
    accept_discovery_without_price: bool = True
    minimum_trust_score_discovery: int = 25
    price_enrich_max_urls: int = 12
    product_page_wait_until: str = "domcontentloaded"
    google_site_fallback: bool = True
    duckduckgo_site_fallback: bool = True
    bing_site_fallback: bool = True
    warmup_home: bool = False
    watch_urls: list[str] = Field(
        default_factory=list,
        description="URLs de produto Shopee (-i.shop.item) para monitorar sem busca.",
    )


class MarketplacesConfig(BaseModel):
    shopee: bool = True
    mercadolivre: bool = True
    google_shopping: bool = True
    amazon: bool = False
    kabum: bool = False
    shopee_options: ShopeeOptionsConfig = Field(default_factory=ShopeeOptionsConfig)

    def enabled_keys(self) -> list[str]:
        mapping = {
            "shopee": self.shopee,
            "mercadolivre": self.mercadolivre,
            "google_shopping": self.google_shopping,
            "amazon": self.amazon,
            "kabum": self.kabum,
        }
        return [k for k, v in mapping.items() if v]


class FiltersConfig(BaseModel):
    only_new_products: bool = True
    only_national_results: bool = True
    minimum_store_rating: float = 4.5
    minimum_store_sales: int = 50


class AlertsConfig(BaseModel):
    minimum_discount_percent: float = 10
    notify_new_lowest_price: bool = True
    notify_new_products: bool = True
    """Menor preço no resumo Telegram: só ofertas com preço total abaixo deste valor (R$)."""
    fallback_max_price: float | None = None

    def effective_fallback_max_price(self, product: ProductConfig) -> float:
        if self.fallback_max_price is not None:
            return self.fallback_max_price
        return product.expected_price_range.max


class SchedulerConfig(BaseModel):
    interval_minutes: int = 15


class ScrapingConfig(BaseModel):
    max_pages: int = 2
    scroll_pause_ms: int = 800
    request_timeout_ms: int = 30000


class TrustConfig(BaseModel):
    minimum_score_to_alert: int = 40
    minimum_score_to_persist: int = 30


class PromotionConfig(BaseModel):
    abnormal_drop_percent: float = 25
    history_days_for_average: int = 30


class AppConfig(BaseModel):
    product: ProductConfig
    marketplaces: MarketplacesConfig
    filters: FiltersConfig
    alerts: AlertsConfig
    scheduler: SchedulerConfig
    scraping: ScrapingConfig = Field(default_factory=ScrapingConfig)
    trust: TrustConfig = Field(default_factory=TrustConfig)
    promotion: PromotionConfig = Field(default_factory=PromotionConfig)

    def effective_interval_minutes(self, settings: Settings | None = None) -> int:
        s = settings or get_settings()
        if s.scheduler_interval_minutes is not None:
            return s.scheduler_interval_minutes
        return self.scheduler.interval_minutes


def load_app_config(path: Path | None = None) -> AppConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    with config_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return AppConfig.model_validate(raw)


@lru_cache
def get_app_config() -> AppConfig:
    return load_app_config()
