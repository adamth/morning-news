"""Unit tests for the LLM module: prompt building, JSON parsing, and the
special-report f-string regression that caused `name 'title' is not defined`.
"""

from __future__ import annotations

import json

import pytest

from app import llm
from app.llm import (
    ArticleInput,
    EpisodeContent,
    MessageInput,
    ReportedLink,
    SpecialReport,
    _build_generation_prompt,
    _parse_episode_content,
    _parse_reported_links,
    prepare_spoken_text,
)


class TestParseEpisodeContent:
    def test_parses_valid_json(self):
        raw = json.dumps({
            "title": "Test Episode",
            "description": "A test.",
            "script": "Hello world.",
            "used_article_ids": [0, 2],
            "used_message_ids": [1],
            "reported_items": ["Book A"],
            "reported_links": [{"title": "Book A", "url": "https://goodreads.com/a"}],
        })

        content = _parse_episode_content(raw)
        assert content.title == "Test Episode"
        assert content.script == "Hello world."
        assert content.used_article_ids == [0, 2]
        assert content.used_message_ids == [1]
        assert content.reported_items == ["Book A"]
        assert len(content.reported_links) == 1
        assert content.reported_links[0].title == "Book A"

    def test_strips_whitespace_from_title(self):
        raw = json.dumps({"title": "  Spaced  ", "script": "Hi."})
        content = _parse_episode_content(raw)
        assert content.title == "Spaced"

    def test_defaults_title_when_missing(self):
        raw = json.dumps({"script": "Hi."})
        content = _parse_episode_content(raw)
        assert content.title == "Daily Briefing"

    def test_raises_on_empty_script(self):
        raw = json.dumps({"title": "X", "script": ""})
        with pytest.raises(llm.LLMError, match="empty script"):
            _parse_episode_content(raw)

    def test_salvages_json_wrapped_in_prose(self):
        raw = 'Here is the episode:\n```json\n{"title": "Salvaged", "script": "Hi."}\n```'
        content = _parse_episode_content(raw)
        assert content.title == "Salvaged"

    def test_raises_when_no_json_found(self):
        with pytest.raises(llm.LLMError, match="did not return JSON"):
            _parse_episode_content("no json here")

    def test_filters_non_integer_article_ids(self):
        raw = json.dumps({
            "script": "Hi.",
            "used_article_ids": [0, "foo", 2, None, "3"],
        })
        content = _parse_episode_content(raw)
        assert content.used_article_ids == [0, 2, 3]

    def test_strips_reported_items_and_filters_empty(self):
        raw = json.dumps({
            "script": "Hi.",
            "reported_items": ["  Book A  ", "", "  ", "Book B"],
        })
        content = _parse_episode_content(raw)
        assert content.reported_items == ["Book A", "Book B"]

    def test_prepare_spoken_text_normalizes_whitespace(self):
        assert prepare_spoken_text("Hello\n\nworld") == "Hello world"
        assert prepare_spoken_text("Tab\there") == "Tab here"
        assert prepare_spoken_text("Multiple   spaces") == "Multiple spaces"
        assert prepare_spoken_text("\\nLiteral\\n") == "Literal"

    def test_prepare_spoken_text_strips_leading_trailing(self):
        assert prepare_spoken_text("  hello  ") == "hello"


class TestParseReportedLinks:
    def test_extracts_valid_entries(self):
        raw = [
            {"title": "Book A", "url": "https://goodreads.com/a"},
            {"title": "Film B", "url": "https://imdb.com/b"},
        ]
        links = _parse_reported_links(raw)
        assert len(links) == 2
        assert links[0] == ReportedLink(title="Book A", url="https://goodreads.com/a")

    def test_skips_missing_title(self):
        raw = [
            {"title": "", "url": "https://example.com"},
            {"url": "https://example.com/other"},
        ]
        links = _parse_reported_links(raw)
        assert links == []

    def test_allows_empty_url(self):
        raw = [{"title": "Some Item", "url": ""}]
        links = _parse_reported_links(raw)
        assert len(links) == 1
        assert links[0].url == ""

    def test_returns_empty_for_non_list(self):
        assert _parse_reported_links(None) == []
        assert _parse_reported_links("not a list") == []
        assert _parse_reported_links({}) == []

    def test_skips_non_dict_entries(self):
        raw = ["string", 42, None, {"title": "OK", "url": "https://x"}]
        links = _parse_reported_links(raw)
        assert len(links) == 1
        assert links[0].title == "OK"

    def test_strips_whitespace(self):
        raw = [{"title": "  Spaced  ", "url": "  https://x.com  "}]
        links = _parse_reported_links(raw)
        assert links[0].title == "Spaced"
        assert links[0].url == "https://x.com"


class TestBuildGenerationPrompt:
    """Regression tests for prompt construction, especially the {title, url}
    f-string bug that caused `name 'title' is not defined`.
    """

    def _base_kwargs(self):
        return dict(
            podcast_title="Morning News",
            date_text="Sunday, July 12, 2026",
            locality="Testville",
            target_min=1.5,
            target_max=3.0,
            priorities_text="(none selected)",
            excluded_topics=[],
            weather_text="sunny",
            market_text="up 2%",
            market_reaction="good day",
            events=["Meeting at 9am"],
            messages=[MessageInput(id=1, text="Hello!")],
            articles=[
                ArticleInput(id=0, title="News Story", publisher="Gazette", content="Body text."),
            ],
        )

    def test_regular_episode_prompt_builds_without_error(self):
        prompt = _build_generation_prompt(**self._base_kwargs())
        assert "Morning News" in prompt
        assert "News Story" in prompt
        assert "sunny" in prompt

    def test_special_report_prompt_contains_literal_title_url(self):
        """The {title, url} placeholder must appear as literal text in the prompt,
        not be evaluated as a Python expression. Regression test for the
        `name 'title' is not defined` bug.
        """

        report = SpecialReport(
            report_type_id="books",
            label="Book recommendations",
            prompt="Recommend books.",
            user_input="I like sci-fi",
        )
        kwargs = self._base_kwargs()
        kwargs["special_report"] = report

        prompt = _build_generation_prompt(**kwargs)

        # The literal text {title, url} must be in the prompt so the LLM
        # sees the JSON shape it should return.
        assert "{title, url}" in prompt

    def test_special_report_prompt_includes_recent_items(self):
        report = SpecialReport(
            report_type_id="books",
            label="Book recommendations",
            prompt="Recommend books.",
            user_input="I like sci-fi",
            recent_items=["Project Hail Mary", "Dune"],
        )
        kwargs = self._base_kwargs()
        kwargs["special_report"] = report

        prompt = _build_generation_prompt(**kwargs)

        assert "Project Hail Mary" in prompt
        assert "Dune" in prompt
        assert "do not repeat" in prompt.lower()

    def test_special_report_prompt_includes_user_input(self):
        report = SpecialReport(
            report_type_id="reflection",
            label="A quiet reflection",
            prompt="Reflect on a theme.",
            user_input="the start of autumn",
        )
        kwargs = self._base_kwargs()
        kwargs["special_report"] = report

        prompt = _build_generation_prompt(**kwargs)

        assert "the start of autumn" in prompt

    def test_special_report_prompt_handles_empty_user_input(self):
        report = SpecialReport(
            report_type_id="true_story",
            label="A true story",
            prompt="Tell a story.",
            user_input="",
        )
        kwargs = self._base_kwargs()
        kwargs["special_report"] = report

        prompt = _build_generation_prompt(**kwargs)
        assert "(none provided)" in prompt

    def test_special_report_prompt_handles_empty_recent_items(self):
        report = SpecialReport(
            report_type_id="books",
            label="Book recommendations",
            prompt="Recommend books.",
            user_input="thrillers",
            recent_items=[],
        )
        kwargs = self._base_kwargs()
        kwargs["special_report"] = report

        prompt = _build_generation_prompt(**kwargs)
        # Should not include the "recently covered" section at all.
        assert "RECENTLY COVERED" not in prompt

    def test_special_report_prompt_contains_reported_links_instructions(self):
        report = SpecialReport(
            report_type_id="books",
            label="Book recommendations",
            prompt="Recommend books.",
            user_input="sci-fi",
        )
        kwargs = self._base_kwargs()
        kwargs["special_report"] = report

        prompt = _build_generation_prompt(**kwargs)

        assert "reported_links" in prompt
        assert "Goodreads" in prompt
        assert "IMDb" in prompt
        assert "Wikipedia" in prompt
