import asyncio

from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger

from app.config.loader import load_app_config
from app.config.settings import get_settings
from app.services.monitor import PriceMonitorService
from app.utils.logging_setup import setup_logging


def _run_cycle() -> None:
    config = load_app_config()
    service = PriceMonitorService(config)
    asyncio.run(service.run_cycle())


def start_scheduler() -> None:
    setup_logging()
    config = load_app_config()
    settings = get_settings()
    interval = config.effective_interval_minutes(settings)
    scheduler = BlockingScheduler()
    scheduler.add_job(
        _run_cycle,
        "interval",
        minutes=interval,
        id="price_monitor",
        max_instances=1,
        coalesce=True,
        next_run_time=None,
    )
    logger.info("Scheduler started — interval {} minutes", interval)
    _run_cycle()
    scheduler.start()
