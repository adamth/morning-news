"""Today's calendar events from a CalDAV server or a public .ics URL."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar

logger = logging.getLogger(__name__)


@dataclass
class CalendarEvent:
    summary: str
    start: datetime | date
    all_day: bool

    def describe(self, timezone: ZoneInfo) -> str:
        if self.all_day:
            return f"{self.summary} (all day)"
        start = self.start
        if isinstance(start, datetime):
            if start.tzinfo is not None:
                start = start.astimezone(timezone)
            return f"{self.summary} at {start.strftime('%-I:%M %p')}"
        return self.summary


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

    events.sort(key=lambda event: (event.all_day is False, str(event.start)))
    return events


def fetch_events(calendar_url: str, timezone_name: str = "UTC") -> list[CalendarEvent]:
    """Fetch today's events. Tries a plain GET (.ics) first, then CalDAV."""

    if not calendar_url.strip():
        return []
    timezone = ZoneInfo(timezone_name) if timezone_name else ZoneInfo("UTC")
    today = datetime.now(timezone).date()

    ical_text = _try_http_ics(calendar_url)
    if ical_text:
        return _events_today(ical_text, today, timezone)

    return _try_caldav(calendar_url, today, timezone)


def _try_http_ics(calendar_url: str) -> str | None:
    try:
        response = httpx.get(calendar_url, timeout=25, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as error:
        logger.info("Direct .ics fetch failed (will try CalDAV): %s", error)
        return None
    text = response.text
    if "BEGIN:VCALENDAR" in text:
        return text
    return None


def _try_caldav(calendar_url: str, today: date, timezone: ZoneInfo) -> list[CalendarEvent]:
    try:
        import caldav
    except ImportError:
        logger.warning("caldav library unavailable; cannot read CalDAV URL")
        return []

    try:
        client = caldav.DAVClient(url=calendar_url)
        principal = client.principal()
        calendars = principal.calendars()
    except Exception as error:  # caldav raises a broad range of errors
        logger.warning("CalDAV connection failed: %s", error)
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
    return events
