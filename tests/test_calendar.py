"""Calendar source tests: labelling, merging, and per-feed selection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from app.sources.calendar import CalendarEvent, CalendarSource, fetch_all_events


def _ics(*entries: tuple[str, datetime]) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0"]
    for summary, start in entries:
        lines += [
            "BEGIN:VEVENT",
            f"SUMMARY:{summary}",
            f"DTSTART:{start.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


class TestEventDescription:
    def test_labels_prefix_the_event(self):
        start = datetime(2026, 3, 4, 9, 30, tzinfo=dt_timezone.utc)
        event = CalendarEvent(summary="Standup", start=start, all_day=False, label="Work")

        assert event.describe(ZoneInfo("UTC")) == "Work: Standup at 9:30 AM"

    def test_unlabelled_events_read_plainly(self):
        start = datetime(2026, 3, 4, 9, 30, tzinfo=dt_timezone.utc)
        event = CalendarEvent(summary="Standup", start=start, all_day=False, label="")

        assert event.describe(ZoneInfo("UTC")) == "Standup at 9:30 AM"


class TestFetchAllEvents:
    def test_merges_calendars_in_time_order_with_labels(self, monkeypatch):
        from app.sources import calendar as calendar_module

        today = datetime.now(dt_timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        payloads = {
            "https://work.example/cal.ics": _ics(("Standup", today + timedelta(hours=9))),
            "https://home.example/cal.ics": _ics(
                ("Dentist", today + timedelta(hours=15)),
                ("School run", today + timedelta(hours=8)),
            ),
        }
        monkeypatch.setattr(
            calendar_module, "_try_http_ics", lambda url, label="": payloads[url]
        )

        events = fetch_all_events(
            [
                CalendarSource(url="https://work.example/cal.ics", label="Work"),
                CalendarSource(url="https://home.example/cal.ics", label="Home"),
            ],
            "UTC",
        )

        assert [event.describe(ZoneInfo("UTC")) for event in events] == [
            "Home: School run at 8:00 AM",
            "Work: Standup at 9:00 AM",
            "Home: Dentist at 3:00 PM",
        ]

    def test_no_calendars_means_no_fetch(self, monkeypatch):
        from app.sources import calendar as calendar_module

        def fail(*args, **kwargs):
            raise AssertionError("should not fetch when there are no calendars")

        monkeypatch.setattr(calendar_module, "_try_http_ics", fail)

        assert fetch_all_events([], "UTC") == []
