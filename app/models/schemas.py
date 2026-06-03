from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TrustLevel(str, Enum):
    LOW = "BAIXA"
    MEDIUM = "MÉDIA"
    HIGH = "ALTA"


class ScrapedProduct(BaseModel):
    marketplace: str
    external_id: str
    title: str
    current_price: float
    original_price: float | None = None
    discount_percent: float | None = None
    shipping_price: float | None = None
    store_name: str | None = None
    rating: float | None = None
    sold_count: int | None = None
    condition: str | None = None
    url: str
    image_url: str | None = None
    is_sponsored: bool = False
    collected_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def total_price(self) -> float:
        return self.current_price + (self.shipping_price or 0.0)


class TrustResult(BaseModel):
    score: int
    level: TrustLevel
    reasons: list[str] = Field(default_factory=list)
    rejected: bool = False


class PromotionAlert(BaseModel):
    alert_type: str
    product_id: int
    title: str
    marketplace: str
    current_price: float
    discount_percent: float | None = None
    historical_average: float | None = None
    store_name: str | None = None
    url: str
    trust_score: int
    trust_level: TrustLevel
    message_extra: str = ""


class CycleLowestOffer(BaseModel):
    title: str
    marketplace: str
    total_price: float
    store_name: str | None = None
    url: str
    trust_score: int = 0
    passed_filters: bool = True
    below_price_cap: bool = False


class CycleDigest(BaseModel):
    main_term: str
    scraped: int
    saved: int
    rejected: int
    alerts: int
    elapsed_ms: int
    fallback_max_price: float = 0.0
    candidates_below_cap: int = 0
    lowest: CycleLowestOffer | None = None
    lowest_passed_filters: bool = False
    lowest_below_cap: bool = False
    marketplace_lines: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    attempts_total: int = 0
    attempts_empty: int = 0
    attempts_failed: int = 0
