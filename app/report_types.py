"""Special report types that can replace or supplement the daily news on a
given weekday (e.g. book recommendations on Mondays).

Each report type contributes a prompt fragment that's spliced into the
episode-generation prompt, plus an optional free-text input the household
fills in so the LLM can tailor suggestions to their taste.
"""

from __future__ import annotations

from dataclasses import dataclass

WEEKDAY_LABELS: tuple[str, ...] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


@dataclass(frozen=True)
class ReportType:
    id: str
    label: str
    hint: str
    prompt: str
    input_label: str
    input_hint: str
    input_placeholder: str
    wants_input: bool = True


REPORT_TYPES: tuple[ReportType, ...] = (
    ReportType(
        id="books",
        label="Book recommendations",
        hint="Suggest two or three books the household might enjoy next.",
        prompt=(
            "Today's episode is BOOK DAY. After the weather (and a brief calendar "
            "reminder if there is one), skip the news entirely and spend the rest "
            "of the episode recommending two or three books the household might "
            "enjoy next. Use the listener's tastes below to pick titles across "
            "genres they already like; don't be afraid to recommend less well "
            "known books. When a recommendation connects to a book "
            "they've enjoyed, say why in a few sentences. For each book give: "
            "title, author, a one-sentence pitch (no spoilers), and a single "
            "line on who'd especially like it. End with a warm sign-off."
        ),
        input_label="Books you've enjoyed",
        input_hint=(
            "List a few books (or authors / genres) you've liked. The host uses "
            "these to pick titles that match your taste."
        ),
        input_placeholder="e.g. The Overstory, anything by Kazuo Ishiguro, cosy mysteries",
    ),
    ReportType(
        id="movies",
        label="Film & TV recommendations",
        hint="Suggest two or three films or shows to watch this week.",
        prompt=(
            "Today's episode is FILM DAY. After the weather (and a brief calendar "
            "reminder if there is one), skip the news entirely and spend the rest "
            "of the episode recommending two or three films or shows the "
            "household might enjoy this week. Use the listener's tastes below to "
            "pick titles across genres they already like; when a recommendation "
            "connects to something they've enjoyed, say why in a few sentences. "
            "For each title give: title, year (if known), a short pitch "
            "(no spoilers). End with a warm sign-off."
        ),
        input_label="Films & shows you've liked",
        input_hint=(
            "List a few films, shows, or genres you've enjoyed. The host uses "
            "these to pick titles that match your taste."
        ),
        input_placeholder="e.g. Past Lives, Severance, slow-burn thrillers",
    ),
    ReportType(
        id="true_story",
        label="A true story",
        hint="Tell one fascinating true story in full.",
        prompt=(
            "Today's episode is TRUE STORY DAY. After the weather (and a brief "
            "calendar reminder if there is one), skip the news entirely and tell "
            "one compelling, self-contained true story. Pick something genuinely "
            "interesting and a little surprising — a moment from history, science, "
            "exploration, or ordinary people doing something remarkable — and "
            "narrate it as a short story with a beginning, middle, and end. Avoid "
            "tragedies that centre on suffering; lean toward wonder, ingenuity, or "
            "serendipity. If the listener named a topic below, pick a story about "
            "it; otherwise choose freely. End with a warm sign-off."
        ),
        input_label="Topics you find fascinating",
        input_hint=(
            "Optional. Name a subject (or a few) and the host will find a true "
            "story about it — space, the sea, a particular place or era, etc."
        ),
        input_placeholder="e.g. the deep sea, forgotten women in science, polar exploration",
    ),
    ReportType(
        id="deep_dive",
        label="News deep dive",
        hint="Pick one big story and explain it properly.",
        prompt=(
            "Today's episode is DEEP DIVE DAY. After the weather (and a brief "
            "calendar reminder if there is one), pick ONE news story from today's "
            "candidates and explain it properly: the background, what's new today, "
            "and why it matters — in three or four short paragraphs of plain "
            "spoken English. Cover at most one or two other very brief headlines "
            "before the deep dive if they're urgent. End with a warm sign-off."
        ),
        input_label="Topics to prioritise",
        input_hint=(
            "Optional. Name a subject (or a few) and the host will prefer deep "
            "dives on it when there's a relevant story today."
        ),
        input_placeholder="e.g. AI policy, local housing, the housing market",
    ),
    ReportType(
        id="reflection",
        label="A quiet reflection",
        hint="A short, gentle piece on a theme — no news.",
        prompt=(
            "Today's episode is REFLECTION DAY. After the weather (and a brief "
            "calendar reminder if there is one), skip the news entirely and offer "
            "a short, gentle spoken reflection on a single theme — the changing "
            "season, a small everyday pleasure, a question worth sitting with. "
            "Keep it under two minutes, warm and unhurried, never preachy. End "
            "with a warm sign-off."
        ),
        input_label="Themes you enjoy",
        input_hint="Optional. Name a theme or two and the host will reflect on one.",
        input_placeholder="e.g. the start of autumn, small kindnesses, the smell of rain",
        wants_input=True,
    ),
)


_REPORT_BY_ID: dict[str, ReportType] = {report_type.id: report_type for report_type in REPORT_TYPES}


def get_report_type(report_type_id: str) -> ReportType | None:
    return _REPORT_BY_ID.get((report_type_id or "").strip())


def is_special(report_type_id: str) -> bool:
    return bool((report_type_id or "").strip()) and (report_type_id or "").strip() in _REPORT_BY_ID
