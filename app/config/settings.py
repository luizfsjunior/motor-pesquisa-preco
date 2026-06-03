from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    headless: bool = True
    browser_start_minimized: bool = True
    database_url: str = "sqlite:///data/prices.db"
    log_level: str = "INFO"
    scheduler_interval_minutes: int | None = None
    shopee_storage_state_path: str = "data/shopee_storage_state.json"
    shopee_persistent_profile: bool = False
    shopee_cdp_url: str = ""
    shopee_cdp_strict: bool = True
    shopee_browser: str = "chrome"
    shopee_interactive: bool = True
    # true = só DuckDuckGo/Bing/Google (GitHub Actions / plano B)
    shopee_fallback_only: bool = False

    @field_validator("scheduler_interval_minutes", mode="before")
    @classmethod
    def empty_scheduler_interval_is_none(cls, value: object) -> object:
        if value == "" or value is None:
            return None
        return value

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token.strip() and self.telegram_chat_id.strip())

    @property
    def sqlite_path(self) -> Path:
        url = self.database_url
        if url.startswith("sqlite:///"):
            rel = url.replace("sqlite:///", "")
            path = Path(rel)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            return path
        return PROJECT_ROOT / "data" / "prices.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
