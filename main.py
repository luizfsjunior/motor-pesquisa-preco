"""Entry point for the price monitoring scheduler."""

from app.scheduler.jobs import start_scheduler

if __name__ == "__main__":
    start_scheduler()
