"""Shared Jinja2 templates instance."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

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


def format_spoken_date(value: datetime, *, include_weekday: bool = True) -> str:
    """Spoken-style date with a comma before the year, e.g. 'Thursday, July 2, 2026'."""

    month_day = f"{value.strftime('%B')} {value.day}"
    year = value.strftime("%Y")
    if include_weekday:
        return f"{value.strftime('%A')}, {month_day}, {year}"
    return f"{month_day}, {year}"


def health_checked_at(timestamp: float | None) -> str:
    if timestamp is None:
        return "not yet"

    checked_at = datetime.fromtimestamp(timestamp)
    return f"{checked_at.strftime('%I:%M %p on %B')} {checked_at.day}"


templates.env.filters["message_status_label"] = message_status_label
templates.env.filters["episode_status_label"] = episode_status_label
templates.env.filters["spoken_date"] = format_spoken_date
templates.env.filters["health_checked_at"] = health_checked_at
