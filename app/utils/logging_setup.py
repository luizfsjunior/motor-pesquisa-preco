import sys
from pathlib import Path

from loguru import logger

from app.config.settings import PROJECT_ROOT, get_settings

LOGS_DIR = PROJECT_ROOT / "logs"


def setup_logging() -> None:
    settings = get_settings()
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
            "<level>{message}</level>"
        ),
    )
    logger.add(
        LOGS_DIR / "scraping_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="14 days",
        level="INFO",
        filter=lambda record: record["extra"].get("category") == "scraping",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )
    logger.add(
        LOGS_DIR / "errors_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    )
    logger.add(
        LOGS_DIR / "performance_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="7 days",
        level="INFO",
        filter=lambda record: record["extra"].get("category") == "performance",
        format="{time:YYYY-MM-DD HH:mm:ss} | {message}",
    )
