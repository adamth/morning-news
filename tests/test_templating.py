"""Displayed timestamps: stored as UTC, read in the household's timezone."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone as dt_timezone
from pathlib import Path

from app.templating import (
    TEMPLATES_DIR,
    format_spoken_date,
    health_checked_at,
    in_timezone,
    templates,
)

# 8:15 pm UTC is already the next morning in Melbourne, which is when an
# episode built for a 6:15 am listen is actually written.
STORED_UTC = datetime(2026, 9, 2, 20, 15)
MELBOURNE = "Australia/Melbourne"


class TestInTimezone:
    def test_a_naive_timestamp_is_read_as_utc(self):
        assert in_timezone(STORED_UTC, MELBOURNE).date() == date(2026, 9, 3)

    def test_the_displayed_date_matches_the_date_the_script_spoke(self):
        spoken = format_spoken_date(in_timezone(STORED_UTC, MELBOURNE))

        assert spoken == "Thursday, September 3, 2026"

    def test_a_utc_household_sees_the_stored_day(self):
        assert in_timezone(STORED_UTC, "UTC").date() == date(2026, 9, 2)

    def test_a_household_west_of_utc_sees_the_earlier_day(self):
        stored = datetime(2026, 9, 3, 4, 30)

        assert in_timezone(stored, "America/Los_Angeles").date() == date(2026, 9, 2)

    def test_an_aware_timestamp_is_converted_rather_than_relabelled(self):
        aware = STORED_UTC.replace(tzinfo=dt_timezone.utc)

        assert in_timezone(aware, MELBOURNE).hour == 6

    def test_an_unusable_timezone_falls_back_to_utc(self):
        for timezone_name in ("", "Mars/Olympus_Mons"):
            assert in_timezone(STORED_UTC, timezone_name).date() == date(2026, 9, 2)


class TestRegisteredFilters:
    def _render(self, source: str, **context) -> str:
        return templates.env.from_string(source).render(**context)

    def test_the_episode_date_filter_chain_is_wired_up(self):
        rendered = self._render(
            "{{ ts | in_timezone(tz) | spoken_date }}", ts=STORED_UTC, tz=MELBOURNE
        )

        assert rendered == "Thursday, September 3, 2026"

    def test_a_missing_household_timezone_does_not_break_the_page(self):
        rendered = self._render("{{ ts | in_timezone(tz) | spoken_date }}", ts=STORED_UTC)

        assert rendered == "Wednesday, September 2, 2026"

    def test_health_check_time_is_shown_in_the_household_timezone(self):
        checked_at = STORED_UTC.replace(tzinfo=dt_timezone.utc).timestamp()

        assert health_checked_at(checked_at, MELBOURNE) == "06:15 AM on September 3"

    def test_health_check_time_reports_a_check_that_never_ran(self):
        assert health_checked_at(None, MELBOURNE) == "not yet"


class TestTemplatesConvertBeforeFormatting:
    """A template that formats a stored timestamp directly shows the UTC day,
    which is the wrong day for most households."""

    @staticmethod
    def _templates() -> list[Path]:
        return sorted(Path(TEMPLATES_DIR).glob("*.html"))

    def test_no_template_formats_a_stored_timestamp_directly(self):
        offenders = [
            path.name
            for path in self._templates()
            if re.search(r"_at(?!\s*\|\s*in_timezone)[^|}]*\.strftime", path.read_text())
        ]

        assert offenders == []

    def test_every_timestamp_conversion_names_the_household_timezone(self):
        offenders = [
            path.name
            for path in self._templates()
            if re.search(r"in_timezone\((?!household_timezone\))", path.read_text())
        ]

        assert offenders == []
