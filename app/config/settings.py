from functools import lru_cache
from pathlib import Path

from pydantic import Field
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
    database_url: str = "sqlite:///data/prices.db"
    log_level: str = "INFO"
    scheduler_interval_minutes: int | None = None

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
