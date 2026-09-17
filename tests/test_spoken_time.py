"""Unit tests for rewriting clock times as the words a narrator should read."""

from __future__ import annotations

import pytest

from app.spoken_time import spell_clock_times


class TestSpellClockTimes:
    @pytest.mark.parametrize(
        ("written", "spoken"),
        [
            ("Standup at 9:00 AM", "Standup at nine o'clock in the morning"),
            ("Dentist at 2:30 PM", "Dentist at two thirty in the afternoon"),
            ("The 8:05 a.m. train", "The eight oh five in the morning train"),
            (
                "Doors at 7:15 p.m., then home.",
                "Doors at seven fifteen in the evening, then home.",
            ),
            ("Kickoff 11:45 PM", "Kickoff eleven forty-five at night"),
            (
                "Open from 9 AM to 5 p.m.",
                "Open from nine o'clock in the morning to five o'clock in the evening.",
            ),
            ("Lunch at 12:00 PM", "Lunch at twelve noon"),
            ("Cutoff is 12:00 AM", "Cutoff is midnight"),
            ("Boarding at 14:45", "Boarding at two forty-five in the afternoon"),
        ],
    )
    def test_spells_times_aloud(self, written, spoken):
        assert spell_clock_times(written) == spoken

    def test_leaves_the_hour_ambiguous_when_no_meridiem_is_given(self):
        assert spell_clock_times("Doors at 8:00.") == "Doors at eight o'clock."

    def test_keeps_the_period_that_ends_a_sentence(self):
        assert spell_clock_times("It starts at 6 p.m. The rest follows.") == (
            "It starts at six o'clock in the evening. The rest follows."
        )

    def test_ignores_numbers_that_are_not_times(self):
        assert spell_clock_times("The vote was 3:1 and 25:00 is not a time") == (
            "The vote was 3:1 and 25:00 is not a time"
        )
