"""Today's calendar events from CalDAV servers or public .ics URLs."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar

from ..episode_log import LogTimer, active_log
from ..http_retry import httpx_request_with_retry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CalendarSource:
    """One subscribed calendar. `label` names it aloud, e.g. "Work"."""

    url: str
    label: str = ""


@dataclass
class CalendarEvent:
    summary: str
    start: datetime | date
    all_day: bool
    label: str = ""

    def describe(self, timezone: ZoneInfo) -> str:
        if self.all_day:
            described = f"{self.summary} (all day)"
        elif isinstance(self.start, datetime):
            start = self.start
            if start.tzinfo is not None:
                start = start.astimezone(timezone)
            described = f"{self.summary} at {start.strftime('%-I:%M %p')}"
        else:
            described = self.summary
        return f"{self.label}: {described}" if self.label else described


def _sort_key(event: CalendarEvent, timezone: ZoneInfo) -> tuple[int, float, str]:
    """All-day events first, then chronological, then by title for a stable order."""

    if event.all_day or not isinstance(event.start, datetime):
        return (0, 0.0, event.summary)
    start = event.start
    local = start.astimezone(timezone) if start.tzinfo else start.replace(tzinfo=timezone)
    return (1, local.timestamp(), event.summary)


def _coerce_start(value) -> tuple[datetime | date, bool]:
    if isinstance(value, datetime):
        return value, False
    if isinstance(value, date):
        return value, True
    return value, False


def _events_today(ical_text: str, today: date, timezone: ZoneInfo) -> list[CalendarEvent]:
    events: list[CalendarEvent] = []
    try:
        calendar = Calendar.from_ical(ical_text)
    except ValueError as error:
        logger.warning("Could not parse calendar payload: %s", error)
        return events

    for component in calendar.walk("VEVENT"):
        dtstart = component.get("dtstart")
        if dtstart is None:
            continue
        start, all_day = _coerce_start(dtstart.dt)
        if all_day and isinstance(start, date) and not isinstance(start, datetime):
            event_date = start
        elif isinstance(start, datetime):
            local_start = start.astimezone(timezone) if start.tzinfo else start.replace(tzinfo=timezone)
            event_date = local_start.date()
        else:
            continue
        if event_date == today:
            summary = str(component.get("summary", "(untitled event)"))
            events.append(CalendarEvent(summary=summary, start=start, all_day=all_day))

    events.sort(key=lambda event: _sort_key(event, timezone))
    return events


def fetch_events(
    calendar_url: str, timezone_name: str = "UTC", label: str = ""
) -> list[CalendarEvent]:
    """Fetch today's events. Tries a plain GET (.ics) first, then CalDAV."""

    if not calendar_url.strip():
        return []
    timezone = ZoneInfo(timezone_name) if timezone_name else ZoneInfo("UTC")
    today = datetime.now(timezone).date()

    ical_text = _try_http_ics(calendar_url, label)
    if ical_text:
        events = _events_today(ical_text, today, timezone)
    else:
        events = _try_caldav(calendar_url, today, timezone, label)
    return [replace(event, label=label) for event in events]


def fetch_all_events(
    sources: Iterable[CalendarSource], timezone_name: str = "UTC"
) -> list[CalendarEvent]:
    """Fetch today's events from every calendar, merged into one ordered list."""

    timezone = ZoneInfo(timezone_name) if timezone_name else ZoneInfo("UTC")
    events: list[CalendarEvent] = []
    for source in sources:
        events.extend(fetch_events(source.url, timezone_name, label=source.label))
    events.sort(key=lambda event: _sort_key(event, timezone))
    return events


def _try_http_ics(calendar_url: str, label: str = "") -> str | None:
    timer = LogTimer.start()
    try:
        response = httpx_request_with_retry(
            lambda: httpx.get(calendar_url, timeout=25, follow_redirects=True)
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        logger.info("Direct .ics fetch failed (will try CalDAV): %s", error)
        audit = active_log()
        if audit is not None:
            audit.record(
                "calendar",
                "Fetch .ics feed",
                status="error",
                summary="Direct fetch failed",
                request={"url": calendar_url, "calendar": label or None},
                response={"error": str(error)},
                duration_ms=timer.elapsed_ms(),
            )
        return None
    text = response.text
    valid = "BEGIN:VCALENDAR" in text
    audit = active_log()
    if audit is not None:
        audit.record(
            "calendar",
            "Fetch .ics feed",
            status="success" if valid else "error",
            summary=f"{len(text)} bytes" if valid else "Not a valid calendar",
            request={"url": calendar_url, "calendar": label or None},
            response={"bytes": len(text), "valid": valid},
            duration_ms=timer.elapsed_ms(),
        )
    if valid:
        return text
    return None


def _try_caldav(
    calendar_url: str, today: date, timezone: ZoneInfo, label: str = ""
) -> list[CalendarEvent]:
    try:
        import caldav
    except ImportError:
        logger.warning("caldav library unavailable; cannot read CalDAV URL")
        return []

    timer = LogTimer.start()
    try:
        client = caldav.DAVClient(url=calendar_url)
        principal = client.principal()
        calendars = principal.calendars()
    except Exception as error:  # caldav raises a broad range of errors
        logger.warning("CalDAV connection failed: %s", error)
        audit = active_log()
        if audit is not None:
            audit.record(
                "calendar",
                "CalDAV connection",
                status="error",
                request={"url": calendar_url, "calendar": label or None},
                response={"error": str(error)},
                duration_ms=timer.elapsed_ms(),
            )
        return []

    start = datetime.combine(today, time.min, tzinfo=timezone)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone)
    events: list[CalendarEvent] = []
    for calendar in calendars:
        try:
            for found in calendar.search(start=start, end=end, event=True, expand=True):
                events.extend(_events_today(found.data, today, timezone))
        except Exception as error:
            logger.warning("CalDAV calendar search failed: %s", error)
    audit = active_log()
    if audit is not None:
        audit.record(
            "calendar",
            "CalDAV search",
            summary=f"{len(events)} event(s) from {len(calendars)} calendar(s)",
            request={"url": calendar_url, "calendar": label or None, "date": today.isoformat()},
            response={"events": [event.describe(timezone) for event in events]},
            duration_ms=timer.elapsed_ms(),
        )
    return events
