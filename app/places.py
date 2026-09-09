"""Home-place matching: which towns count as "ours" for local relevance.

A listener's suburb sits inside a council, a region, and a state, and news
feeds happily mix all four. Google News' regional search in particular returns
state-wide volume (a query for "Victoria" comes back with ~100 stories a day),
which buries the handful that actually concern the listener's own ridge.

`home_places` is the listener's ordered list of nearby town and area names.
It is used three ways: to build tightly-scoped Google News searches instead of
a state-wide firehose, to rank candidate articles before they reach the LLM,
and to tell the LLM which stories are genuinely local.
"""

from __future__ import annotations

import re
from functools import lru_cache

# A title mention is much stronger evidence than a passing body mention.
_TITLE_WEIGHT = 3
_BODY_WEIGHT = 1
# Long bodies mention neighbouring towns in passing; cap their contribution so
# one rambling article can't outrank a story actually about a home town.
_MAX_BODY_HITS = 3


def parse_places(raw: str) -> list[str]:
    """Return cleaned place names from a comma-separated settings value.

    Order is preserved (the listener lists closest first) and duplicates are
    dropped case-insensitively.
    """

    places: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        name = " ".join(part.split())
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        places.append(name)
    return places


def serialize_places(places: list[str]) -> str:
    """Persist a place list back to the comma-separated settings value."""

    return ", ".join(parse_places(", ".join(places)))


@lru_cache(maxsize=256)
def _pattern(place: str) -> re.Pattern[str]:
    """Word-bounded, case-insensitive matcher for one place name.

    Bounded so "Belgrave" does not match "Belgraves", while still matching
    inside compounds like "Olinda-Ferny Creek" and "Belgrave Heights".
    """

    return re.compile(rf"\b{re.escape(place)}\b", re.IGNORECASE)


def match_places(text: str, places: list[str]) -> list[str]:
    """Return the home places mentioned in `text`, in home-place order."""

    if not text or not places:
        return []
    return [place for place in places if _pattern(place).search(text)]


def score_text(*, title: str, body: str, places: list[str]) -> int:
    """Score how local a story is: title mentions count for more than body ones."""

    if not places:
        return 0
    score = _TITLE_WEIGHT * len(match_places(title, places))
    body_hits = len(match_places(body, places))
    return score + _BODY_WEIGHT * min(body_hits, _MAX_BODY_HITS)
