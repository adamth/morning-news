"""Clock times rewritten as words so TTS reads 8:00 as "eight o'clock"."""

from __future__ import annotations

import re

_ONES = (
    "",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty"}

# The abbreviation's final dot is only dropped when the sentence visibly continues, so
# "at 5 p.m." keeps the period that ends it.
_MERIDIEM = r"\.?\s?[mM]\b(?:\.(?=\s*[a-z0-9,;:]))?"

_CLOCK_TIME = re.compile(
    rf"\b(?P<hour>\d{{1,2}}):(?P<minute>[0-5]\d)(?:\s*(?P<meridiem>[apAP]){_MERIDIEM})?"
    rf"|\b(?P<bare_hour>\d{{1,2}})\s*(?P<bare_meridiem>[apAP]){_MERIDIEM}"
)


def _number_words(value: int) -> str:
    if value < 20:
        return _ONES[value]
    tens, ones = divmod(value, 10)
    return f"{_TENS[tens]}-{_ONES[ones]}" if ones else _TENS[tens]


def _daypart(hour: int) -> str:
    if hour < 12:
        return "in the morning"
    if hour < 17:
        return "in the afternoon"
    if hour < 21:
        return "in the evening"
    return "at night"


def _spoken_time(hour: int, minute: int, *, is_daypart_known: bool) -> str:
    if minute == 0 and hour == 0:
        return "midnight"
    if minute == 0 and hour == 12:
        return "twelve noon"
    hour_words = _number_words(hour % 12 or 12)
    if minute == 0:
        clock = f"{hour_words} o'clock"
    elif minute < 10:
        clock = f"{hour_words} oh {_number_words(minute)}"
    else:
        clock = f"{hour_words} {_number_words(minute)}"
    return f"{clock} {_daypart(hour)}" if is_daypart_known else clock


def _replace(match: re.Match[str]) -> str:
    hour_text = match.group("hour") or match.group("bare_hour")
    minute_text = match.group("minute") or "0"
    meridiem = match.group("meridiem") or match.group("bare_meridiem") or ""
    hour, minute = int(hour_text), int(minute_text)
    if hour > 23 or (meridiem and hour > 12):
        return match.group(0)
    if meridiem.lower() == "p" and hour < 12:
        hour += 12
    elif meridiem.lower() == "a" and hour == 12:
        hour = 0
    return _spoken_time(hour, minute, is_daypart_known=bool(meridiem) or hour > 12)


def spell_clock_times(text: str) -> str:
    """Rewrite clock times such as "8:00 AM" or "14:30" as spoken words."""

    return _CLOCK_TIME.sub(_replace, text)
