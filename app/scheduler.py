from __future__ import annotations

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

from app.ingest import run_ingestion

logger = logging.getLogger("job_vc.scheduler")

SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"

# Comma-separated UTC hours to run ingestion, e.g. "8,20"
_SCHEDULE_HOURS = [
    int(h.strip())
    for h in os.getenv("SCHEDULE_HOURS", "8,20").split(",")
    if h.strip().isdigit()
]


def _ingest_job() -> None:
    logger.info("Scheduled ingest firing")
    try:
        stats = run_ingestion()
        logger.info("Scheduled ingest done | stats=%s", stats)
    except Exception:
        logger.exception("Scheduled ingest failed")


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    for hour in _SCHEDULE_HOURS:
        scheduler.add_job(
            _ingest_job,
            trigger="cron",
            hour=hour,
            minute=0,
            coalesce=True,      # skip missed runs instead of catching up
            max_instances=1,    # never run two ingests simultaneously
            id=f"ingest_{hour:02d}00",
            name=f"Daily ingest at {hour:02d}:00 UTC",
        )
    return scheduler
