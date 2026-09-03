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


class TestRecurringEvents:
    """A recurring VEVENT carries only its first DTSTART, so today's occurrence
    has to be derived from the rule rather than read off the component."""

    @staticmethod
    def _describe_today(ics: str, timezone_name: str = "Australia/Melbourne") -> list[str]:
        from app.sources.calendar import _events_today

        timezone = ZoneInfo(timezone_name)
        today = datetime.now(timezone).date()
        return [event.describe(timezone) for event in _events_today(ics, today, timezone)]

    @staticmethod
    def _recurring_ics(*blocks: str) -> str:
        return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", *blocks, "END:VCALENDAR"])

    @staticmethod
    def _daily_at(hour: int, minute: int, summary: str, *, days_ago: int = 90) -> str:
        started = datetime.now(ZoneInfo("Australia/Melbourne")) - timedelta(days=days_ago)
        return "\r\n".join([
            "BEGIN:VEVENT",
            f"UID:{summary.replace(' ', '')}@example.com",
            f"DTSTART;TZID=Australia/Melbourne:{started.strftime('%Y%m%d')}T"
            f"{hour:02d}{minute:02d}00",
            f"DTEND;TZID=Australia/Melbourne:{started.strftime('%Y%m%d')}T"
            f"{hour:02d}{minute + 15:02d}00",
            "RRULE:FREQ=DAILY",
            f"SUMMARY:{summary}",
            "END:VEVENT",
        ])

    def test_a_daily_standup_added_months_ago_still_appears_today(self):
        ics = self._recurring_ics(self._daily_at(9, 0, "Standup"))

        assert self._describe_today(ics) == ["Standup at 9:00 AM"]

    def test_short_early_recurring_meetings_are_all_kept_in_time_order(self):
        ics = self._recurring_ics(
            self._daily_at(9, 15, "Sam one on one"),
            self._daily_at(8, 30, "Triage"),
            self._daily_at(9, 0, "Standup"),
        )

        assert self._describe_today(ics) == [
            "Triage at 8:30 AM",
            "Standup at 9:00 AM",
            "Sam one on one at 9:15 AM",
        ]

    def test_an_excluded_occurrence_stays_excluded(self):
        timezone = ZoneInfo("Australia/Melbourne")
        today = datetime.now(timezone).date()
        started = datetime.now(timezone) - timedelta(days=90)
        ics = self._recurring_ics("\r\n".join([
            "BEGIN:VEVENT",
            "UID:cancelled@example.com",
            f"DTSTART;TZID=Australia/Melbourne:{started.strftime('%Y%m%d')}T090000",
            f"DTEND;TZID=Australia/Melbourne:{started.strftime('%Y%m%d')}T091500",
            "RRULE:FREQ=DAILY",
            f"EXDATE;TZID=Australia/Melbourne:{today.strftime('%Y%m%d')}T090000",
            "SUMMARY:Cancelled today",
            "END:VEVENT",
        ]))

        assert self._describe_today(ics) == []

    def test_a_multi_day_event_underway_is_mentioned_without_a_start_time(self):
        timezone = ZoneInfo("Australia/Melbourne")
        today = datetime.now(timezone).date()
        ics = self._recurring_ics("\r\n".join([
            "BEGIN:VEVENT",
            "UID:offsite@example.com",
            f"DTSTART;VALUE=DATE:{(today - timedelta(days=2)).strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(today + timedelta(days=2)).strftime('%Y%m%d')}",
            "SUMMARY:Offsite",
            "END:VEVENT",
        ]))

        assert self._describe_today(ics) == ["Offsite (continues today)"]

    def test_a_one_off_event_on_another_day_is_left_out(self):
        timezone = ZoneInfo("Australia/Melbourne")
        tomorrow = datetime.now(timezone) + timedelta(days=1)
        ics = self._recurring_ics("\r\n".join([
            "BEGIN:VEVENT",
            "UID:tomorrow@example.com",
            f"DTSTART;TZID=Australia/Melbourne:{tomorrow.strftime('%Y%m%d')}T090000",
            f"DTEND;TZID=Australia/Melbourne:{tomorrow.strftime('%Y%m%d')}T093000",
            "SUMMARY:Not today",
            "END:VEVENT",
        ]))

        assert self._describe_today(ics) == []
