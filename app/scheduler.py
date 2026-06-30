"""APScheduler-based daily cron, reconfigurable at runtime from the web UI."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session

from .db import engine, get_settings
from .health import refresh_health_report
from .pipeline import generate_episode_background

logger = logging.getLogger(__name__)

_JOB_ID = "daily-episode"
_HEALTH_JOB_ID = "health-check"
_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.start()
    reschedule()
    schedule_health_checks()
    refresh_health_report(force_all=False)


def schedule_health_checks() -> None:
    """Run dependency health checks weekly; passing API keys are not re-probed for seven days."""

    if _scheduler is None:
        return
    _scheduler.add_job(
        _run_health_check_job,
        trigger=CronTrigger(day_of_week="sun", hour=3, minute=15),
        id=_HEALTH_JOB_ID,
        replace_existing=True,
        misfire_grace_time=86400,
        coalesce=True,
        max_instances=1,
    )
    logger.info("Health checks scheduled weekly on Sundays at 03:15")


def _run_health_check_job() -> None:
    report = refresh_health_report(force_all=False)
    logger.info(
        "Health check completed with %d issue(s)",
        report.issue_count,
    )


def reschedule() -> None:
    """(Re)apply the daily trigger from the current Settings row."""

    if _scheduler is None:
        return
    with Session(engine) as session:
        settings = get_settings(session)
        hour, minute, tz = settings.schedule_hour, settings.schedule_minute, settings.timezone

    trigger = CronTrigger(hour=hour, minute=minute, timezone=tz or "UTC")
    _scheduler.add_job(
        generate_episode_background,
        trigger=trigger,
        id=_JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    logger.info("Daily episode scheduled for %02d:%02d %s", hour, minute, tz)


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
