"""Shared Jinja2 templates instance."""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_MESSAGE_STATUS_LABELS = {
    "pending": "Queued for next episode",
    "resolved": "Read aloud",
}

_EPISODE_STATUS_LABELS = {
    "pending": "Waiting to build",
    "generating": "Building now…",
    "ready": "Ready to listen",
    "failed": "Something went wrong",
}


def message_status_label(status: str) -> str:
    return _MESSAGE_STATUS_LABELS.get(status, status.replace("_", " ").capitalize())


def episode_status_label(status: str) -> str:
    return _EPISODE_STATUS_LABELS.get(status, status.replace("_", " ").capitalize())


def in_timezone(value: datetime, timezone_name: str = "UTC") -> datetime:
    """Read a stored timestamp in the household's timezone.

    Timestamps are written naive by `utcnow()`, so a template that formats one
    directly shows the UTC day — a day behind for a household east of UTC, whose
    morning episode is built the previous evening UTC.
    """

    try:
        household = ZoneInfo(timezone_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        household = ZoneInfo("UTC")
    aware = value if value.tzinfo is not None else value.replace(tzinfo=dt_timezone.utc)
    return aware.astimezone(household)


def format_spoken_date(value: datetime, *, include_weekday: bool = True) -> str:
    """Spoken-style date with a comma before the year, e.g. 'Thursday, July 2, 2026'."""

    month_day = f"{value.strftime('%B')} {value.day}"
    year = value.strftime("%Y")
    if include_weekday:
        return f"{value.strftime('%A')}, {month_day}, {year}"
    return f"{month_day}, {year}"


def health_checked_at(timestamp: float | None, timezone_name: str = "UTC") -> str:
    if timestamp is None:
        return "not yet"

    checked_at = in_timezone(datetime.fromtimestamp(timestamp, dt_timezone.utc), timezone_name)
    return f"{checked_at.strftime('%I:%M %p on %B')} {checked_at.day}"


templates.env.filters["message_status_label"] = message_status_label
templates.env.filters["episode_status_label"] = episode_status_label
templates.env.filters["in_timezone"] = in_timezone
templates.env.filters["spoken_date"] = format_spoken_date
templates.env.filters["health_checked_at"] = health_checked_at
