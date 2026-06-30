"""Predefined news categories for soft story prioritization."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NewsCategory:
    id: str
    label: str
    hint: str


NEWS_CATEGORIES: tuple[NewsCategory, ...] = (
    NewsCategory("local", "Local & community", "town/council/neighbourhood stories"),
    NewsCategory("regional", "Regional news", "state or wider-area coverage"),
    NewsCategory("politics", "Politics & government", "elections, policy, parliament"),
    NewsCategory("world", "World news", "international events and diplomacy"),
    NewsCategory("business", "Business & economy", "markets, companies, jobs, cost of living"),
    NewsCategory("technology", "Technology", "gadgets, software, AI, startups"),
    NewsCategory("science", "Science & research", "discoveries, space, studies"),
    NewsCategory("health", "Health & medicine", "public health, hospitals, wellbeing"),
    NewsCategory("environment", "Environment & climate", "weather events, conservation, energy"),
    NewsCategory("sports", "Sports", "local and professional sport"),
    NewsCategory("arts", "Arts & culture", "music, theatre, museums, literature"),
    NewsCategory("entertainment", "Entertainment", "film, TV, games, celebrity"),
    NewsCategory("crime", "Crime & courts", "police, legal cases, safety"),
    NewsCategory("education", "Education", "schools, universities, students"),
    NewsCategory("infrastructure", "Transport & infrastructure", "roads, rail, major projects"),
    NewsCategory("housing", "Housing & property", "real estate, rentals, planning"),
    NewsCategory("human_interest", "Human interest", "profiles, community wins, oddities"),
    NewsCategory("food", "Food & dining", "restaurants, agriculture, food industry"),
)

_CATEGORY_BY_ID = {category.id: category for category in NEWS_CATEGORIES}


def parse_selected(raw: str) -> list[str]:
    """Return valid category ids from a comma-separated settings value."""

    if not raw.strip():
        return []
    return [
        category_id
        for part in raw.split(",")
        if (category_id := part.strip()) in _CATEGORY_BY_ID
    ]


def serialize_selected(category_ids: list[str]) -> str:
    """Persist only known category ids, in catalog order."""

    selected = set(category_ids)
    return ",".join(category.id for category in NEWS_CATEGORIES if category.id in selected)


def format_priorities(selected_ids: list[str]) -> str:
    """Build LLM guidance from the user's selected categories."""

    if not selected_ids:
        return (
            "(none selected — choose a balanced mix of the most newsworthy stories "
            "for the listener's area)"
        )

    lines = [
        f"- {category.label} ({category.hint})"
        for category_id in selected_ids
        if (category := _CATEGORY_BY_ID.get(category_id)) is not None
    ]
    return "\n".join(lines)
