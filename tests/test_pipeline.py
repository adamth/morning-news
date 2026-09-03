"""End-to-end pipeline tests.

These exercise the full generate_episode() flow with every external dependency
(news, weather, stocks, calendar, LLM, TTS, ffmpeg) mocked. The goal is to
catch regressions in the pipeline's orchestration: data flow between stages,
episode persistence, audit logging, message resolution, and special-report
handling.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone

import pytest
from sqlmodel import select

from app import pipeline as pipeline_module
from app.credentials import Credentials
from app.db import (
    CalendarFeed,
    Episode,
    EpisodeArticle,
    EpisodeLogEntry,
    EpisodeStatus,
    Message,
    MessageStatus,
    ReportedItem,
    Settings,
    Source,
    User,
    WatchlistItem,
    WeeklyReport,
)


# ---------------------------------------------------------------------------
# Regular episode (no special report)
# ---------------------------------------------------------------------------


class TestRegularEpisodeGeneration:
    def test_generates_episode_with_ready_status(self, db_session, settings, mock_pipeline_env):
        episode = pipeline_module.generate_episode(db_session)

        assert episode.status == EpisodeStatus.ready
        assert episode.title == "Morning News for Today"
        assert episode.script != ""
        assert episode.audio_path is not None
        assert episode.audio_path.endswith(".mp3")
        assert episode.duration_seconds == 60.0
        assert episode.error is None

    def test_labelled_events_from_every_calendar_reach_the_episode(
        self, db_session, settings, mock_pipeline_env, monkeypatch
    ):
        from app.sources.calendar import CalendarEvent

        db_session.add(CalendarFeed(url="https://work.example/cal.ics", label="Work"))
        db_session.add(CalendarFeed(url="https://home.example/cal.ics", label="Home"))
        db_session.commit()

        def stub_fetch_all_events(sources, timezone_name="UTC"):
            return [
                CalendarEvent(
                    summary=f"{source.label} thing",
                    start=datetime(2026, 3, 4, 9, 0, tzinfo=timezone.utc),
                    all_day=False,
                    label=source.label,
                )
                for source in sources
            ]

        monkeypatch.setattr(pipeline_module, "fetch_all_events", stub_fetch_all_events)

        episode = pipeline_module.generate_episode(db_session)

        assert episode.events_summary == "Work: Work thing at 9:00 AM; Home: Home thing at 9:00 AM"

    def test_persists_show_note_articles(self, db_session, settings, mock_pipeline_env, make_episode_json):
        # The mock LLM returns used_article_ids=[0]; article 0 is "City council".
        pipeline_module.generate_episode(db_session)

        articles = db_session.exec(select(EpisodeArticle)).all()
        assert len(articles) == 1
        assert articles[0].title == "City council approves new park"
        assert articles[0].publisher == "Test Gazette"
        assert articles[0].url == "https://example.com/park"

    def test_stores_weather_and_market_summaries(self, db_session, settings, mock_pipeline_env, monkeypatch):
        # Enable stocks and add a watchlist item
        settings.stocks_enabled = True
        db_session.add(WatchlistItem(symbol="AAPL", label="Apple", enabled=True))
        db_session.add(settings)
        db_session.commit()

        episode = pipeline_module.generate_episode(db_session)

        assert "clear sky" in episode.weather_summary
        assert episode.market_summary  # non-empty when stocks enabled

    def test_records_audit_log_entries_for_each_stage(self, db_session, settings, mock_pipeline_env):
        episode = pipeline_module.generate_episode(db_session)

        entries = db_session.exec(
            select(EpisodeLogEntry).where(EpisodeLogEntry.episode_id == episode.id)
        ).all()

        operations = [entry.operation for entry in entries]
        assert "Start generation" in operations
        assert "Configure news sources" in operations
        assert "Gather articles" in operations
        assert "Write episode script" in operations
        assert "Synthesize narration" in operations
        assert "Assemble episode audio" in operations
        assert "Complete generation" in operations

    def test_resolves_pending_messages(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json):
        user = User(username="alice", password_hash="x")
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        msg = Message(author_user_id=user.id, text="Happy birthday!")
        db_session.add(msg)
        db_session.commit()
        db_session.refresh(msg)

        # Configure the LLM to include the message
        mock_llm["default_response"]["used_message_ids"] = [msg.id]
        mock_llm["default_response"]["script"] = "Happy birthday from Alice."
        pipeline_module.generate_episode(db_session)

        db_session.refresh(msg)
        assert msg.status == MessageStatus.resolved
        assert msg.episode_id is not None
        assert msg.resolved_at is not None

    def test_skips_news_from_disabled_sources(self, db_session, settings, mock_pipeline_env):
        # Add a disabled source - it should not be used
        db_session.add(Source(url="https://disabled.example/feed", name="Disabled", enabled=False))
        db_session.add(settings)
        db_session.commit()

        episode = pipeline_module.generate_episode(db_session)
        assert episode.status == EpisodeStatus.ready

    def test_news_sources_with_locality_config(self, db_session, settings, mock_pipeline_env):
        settings.locality = "Sydney"
        settings.admin1 = "New South Wales"
        settings.country = "Australia"
        settings.news_gl = "AU"
        db_session.add(settings)
        db_session.commit()

        episode = pipeline_module.generate_episode(db_session)
        assert episode.status == EpisodeStatus.ready


# ---------------------------------------------------------------------------
# Special report episode (books, films, true story, deep dive, reflection)
# ---------------------------------------------------------------------------


class TestSpecialReportEpisode:
    def test_books_report_persists_reported_items_and_links(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json):
        # Sunday (weekday 6) = book day
        db_session.add(WeeklyReport(day_of_week=6, report_type="books", user_input="I like sci-fi"))
        db_session.commit()

        mock_llm["_state"]["response"] = json.loads(make_episode_json(
            title="Book Day",
            description="Book recommendations for you.",
            script="Today is book day. I recommend Project Hail Mary by Andy Weir.",
            used_article_ids=[],
            used_message_ids=[],
            reported_items=["Project Hail Mary"],
            reported_links=[
                {"title": "Project Hail Mary", "url": "https://www.goodreads.com/book/show/54493401-project-hail-mary"},
            ],
        ))

        # Force "today" to be a Sunday
        original_now = datetime.now
        try:
            import app.pipeline as pl
            # The pipeline uses datetime.now(timezone); we can't easily monkeypatch
            # that, so set the WeeklyReport to match today's weekday instead.
            today_weekday = datetime.now().weekday()
        finally:
            pass

        # Update the weekly report to match today's weekday so it triggers
        db_session.exec(select(WeeklyReport)).all()  # warm up
        wr = db_session.exec(select(WeeklyReport)).first()
        wr.day_of_week = today_weekday
        db_session.add(wr)
        db_session.commit()

        episode = pipeline_module.generate_episode(db_session)

        assert episode.status == EpisodeStatus.ready
        assert episode.title == "Book Day"

        reported = db_session.exec(select(ReportedItem)).all()
        assert len(reported) == 1
        assert reported[0].item == "Project Hail Mary"
        assert reported[0].url == "https://www.goodreads.com/book/show/54493401-project-hail-mary"
        assert reported[0].report_type == "books"
        assert reported[0].episode_id == episode.id

    def test_reported_links_without_url_still_persisted(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json):
        today_weekday = datetime.now().weekday()
        db_session.add(WeeklyReport(day_of_week=today_weekday, report_type="true_story", user_input="space"))
        db_session.commit()

        mock_llm["_state"]["response"] = json.loads(make_episode_json(
            title="True Story Day",
            script="Today I want to tell you about Apollo 11.",
            reported_items=["Apollo 11"],
            reported_links=[
                {"title": "Apollo 11", "url": ""},
            ],
        ))

        episode = pipeline_module.generate_episode(db_session)

        reported = db_session.exec(select(ReportedItem)).all()
        assert len(reported) == 1
        assert reported[0].item == "Apollo 11"
        assert reported[0].url == ""

    def test_reported_link_only_items_are_captured(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json):
        """Items appearing only in reported_links (not in reported_items) should still be saved."""

        today_weekday = datetime.now().weekday()
        db_session.add(WeeklyReport(day_of_week=today_weekday, report_type="movies", user_input="sci-fi"))
        db_session.commit()

        mock_llm["_state"]["response"] = json.loads(make_episode_json(
            title="Film Day",
            script="Watch Dune Part Two.",
            reported_items=[],
            reported_links=[
                {"title": "Dune Part Two", "url": "https://www.imdb.com/title/tt15239678/"},
            ],
        ))

        pipeline_module.generate_episode(db_session)

        reported = db_session.exec(select(ReportedItem)).all()
        assert len(reported) == 1
        assert reported[0].item == "Dune Part Two"

    def test_no_special_report_when_not_configured(self, db_session, settings, mock_pipeline_env):
        episode = pipeline_module.generate_episode(db_session)
        # Default mock LLM returns empty reported_items/links
        reported = db_session.exec(select(ReportedItem)).all()
        assert len(reported) == 0

    def test_covered_items_passed_to_llm(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json):
        today_weekday = datetime.now().weekday()
        db_session.add(WeeklyReport(day_of_week=today_weekday, report_type="books", user_input="thrillers"))
        db_session.commit()

        # Seed a previously reported item
        episode = Episode(title="Old episode", status=EpisodeStatus.ready)
        db_session.add(episode)
        db_session.commit()
        db_session.refresh(episode)
        db_session.add(ReportedItem(report_type="books", item="The Silent Patient", url="", episode_id=episode.id))
        db_session.commit()

        pipeline_module.generate_episode(db_session)

        llm_prompt = mock_llm["calls"][-1]["user"]
        assert "The Silent Patient" in llm_prompt
        assert "do not repeat" in llm_prompt.lower()

    def test_whole_story_history_passed_to_llm(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json):
        """Every past story is excluded, not just the most recent handful."""

        today_weekday = datetime.now().weekday()
        db_session.add(WeeklyReport(day_of_week=today_weekday, report_type="true_story", user_input=""))
        db_session.commit()

        episode = Episode(title="Old episode", status=EpisodeStatus.ready)
        db_session.add(episode)
        db_session.commit()
        db_session.refresh(episode)
        for index in range(30):
            db_session.add(
                ReportedItem(report_type="true_story", item=f"Story {index}", episode_id=episode.id)
            )
        db_session.commit()

        pipeline_module.generate_episode(db_session)

        llm_prompt = mock_llm["calls"][-1]["user"]
        for index in range(30):
            assert f"Story {index}" in llm_prompt

    def test_variety_axis_passed_to_llm(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json):
        from app.report_types import get_report_type

        today_weekday = datetime.now().weekday()
        db_session.add(WeeklyReport(day_of_week=today_weekday, report_type="true_story", user_input=""))
        db_session.commit()

        pipeline_module.generate_episode(db_session)

        llm_prompt = mock_llm["calls"][-1]["user"]
        axes = get_report_type("true_story").variety_axes
        assert any(axis in llm_prompt for axis in axes)

    def test_special_report_without_reported_items_falls_back_to_title(
        self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json
    ):
        """A silent model must still leave a record, or the story can recur."""

        today_weekday = datetime.now().weekday()
        db_session.add(WeeklyReport(day_of_week=today_weekday, report_type="true_story", user_input=""))
        db_session.commit()

        mock_llm["_state"]["response"] = json.loads(make_episode_json(
            title="The Halifax Explosion Tree",
            script="Today, a story about a tree.",
            reported_items=[],
            reported_links=[],
        ))

        pipeline_module.generate_episode(db_session)

        reported = db_session.exec(select(ReportedItem)).all()
        assert [row.item for row in reported] == ["The Halifax Explosion Tree"]


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


class TestMarketComment:
    @staticmethod
    def _enable_stocks(db_session, settings):
        settings.stocks_enabled = True
        db_session.add(WatchlistItem(symbol="AAPL", label="Apple", enabled=True))
        db_session.add(settings)
        db_session.commit()

    def test_market_comment_persisted_on_episode(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json):
        self._enable_stocks(db_session, settings)
        mock_llm["_state"]["response"] = json.loads(make_episode_json(
            market_comment="The watchlist woke up on the right side of the bed.",
        ))

        episode = pipeline_module.generate_episode(db_session)

        assert episode.market_comment == "The watchlist woke up on the right side of the bed."

    def test_past_market_comments_passed_to_llm(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json):
        self._enable_stocks(db_session, settings)
        db_session.add(
            Episode(
                title="Yesterday",
                status=EpisodeStatus.ready,
                market_comment="Flat day. Your watchlist is napping.",
            )
        )
        db_session.commit()

        pipeline_module.generate_episode(db_session)

        llm_prompt = mock_llm["calls"][-1]["user"]
        assert "Flat day. Your watchlist is napping." in llm_prompt
        assert "MARKET ASIDES ALREADY USED" in llm_prompt

    def test_market_comment_not_stored_without_a_market_segment(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json):
        """Stocks are off, so a comment the model invented anyway must not be banked."""

        mock_llm["_state"]["response"] = json.loads(make_episode_json(
            market_comment="A stray aside about nothing.",
        ))

        episode = pipeline_module.generate_episode(db_session)

        assert episode.market_summary == ""
        assert episode.market_comment == ""


class TestCalendarCoverage:
    @staticmethod
    def _with_events(monkeypatch, *summaries):
        from app.sources.calendar import CalendarEvent

        def stub_fetch_all_events(sources, timezone_name="UTC"):
            return [
                CalendarEvent(
                    summary=summary,
                    start=datetime(2026, 3, 4, 9, 0, tzinfo=timezone.utc),
                    all_day=False,
                )
                for summary in summaries
            ]

        monkeypatch.setattr(pipeline_module, "fetch_all_events", stub_fetch_all_events)

    def test_no_retry_when_every_event_is_mentioned(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json, monkeypatch):
        self._with_events(monkeypatch, "Standup")
        mock_llm["_state"]["response"] = json.loads(make_episode_json(used_event_ids=[0]))

        pipeline_module.generate_episode(db_session)

        script_calls = [call for call in mock_llm["calls"] if "CALENDAR EVENTS TODAY" in call["user"]]
        assert len(script_calls) == 1

    def test_dropped_event_triggers_a_retry_naming_it(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json, monkeypatch):
        self._with_events(monkeypatch, "Standup", "Dentist")
        mock_llm["_state"]["response"] = json.loads(make_episode_json(used_event_ids=[1]))

        pipeline_module.generate_episode(db_session)

        script_calls = [call for call in mock_llm["calls"] if "CALENDAR EVENTS TODAY" in call["user"]]
        assert len(script_calls) == 2
        retry_prompt = script_calls[-1]["user"]
        assert "EVENTS YOUR LAST DRAFT LEFT OUT" in retry_prompt
        assert "Standup at 9:00 AM" in retry_prompt
        assert "Dentist" not in retry_prompt.split("EVENTS YOUR LAST DRAFT LEFT OUT")[1]

    def test_retries_at_most_once(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json, monkeypatch):
        """The stub never reports an event, so coverage can never be satisfied."""

        self._with_events(monkeypatch, "Standup")
        mock_llm["_state"]["response"] = json.loads(make_episode_json(used_event_ids=[]))

        episode = pipeline_module.generate_episode(db_session)

        script_calls = [call for call in mock_llm["calls"] if "CALENDAR EVENTS TODAY" in call["user"]]
        assert len(script_calls) == 2
        assert episode.status == EpisodeStatus.ready

    def test_better_retry_replaces_the_first_draft(self, db_session, settings, mock_pipeline_env, mock_llm, monkeypatch, make_episode_json):
        from app import llm as llm_module

        self._with_events(monkeypatch, "Standup", "Dentist")
        drafts = [
            make_episode_json(title="Missed one", used_event_ids=[0]),
            make_episode_json(title="Covered both", used_event_ids=[0, 1]),
        ]

        def stub_chat_completion(*, user, **kwargs):
            mock_llm["calls"].append({"user": user})
            if "CALENDAR EVENTS TODAY" not in user:
                return drafts[-1]
            return drafts.pop(0) if len(drafts) > 1 else drafts[0]

        monkeypatch.setattr(llm_module, "_chat_completion", stub_chat_completion)

        episode = pipeline_module.generate_episode(db_session)

        assert episode.title == "Covered both"

    def test_missed_events_are_found_by_position(self):
        from app.pipeline import _missed_events

        events = ["Standup at 9:00 AM", "Dentist at 2:30 PM", "Pickup at 3:30 PM"]

        assert _missed_events(events, [0, 2]) == ["Dentist at 2:30 PM"]
        assert _missed_events(events, [0, 1, 2]) == []
        assert _missed_events(events, []) == events


class TestWeatherComments:
    def test_weather_comment_persisted_on_episode(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json):
        mock_llm["_state"]["response"] = json.loads(make_episode_json(
            weather_comment="Warm enough to leave the windows open all day.",
        ))

        episode = pipeline_module.generate_episode(db_session)

        assert episode.weather_comment == "Warm enough to leave the windows open all day."

    def test_past_weather_comments_passed_to_llm(self, db_session, settings, mock_pipeline_env, mock_llm):
        db_session.add(
            Episode(
                title="Yesterday",
                status=EpisodeStatus.ready,
                weather_comment="The kind of grey that never quite commits to rain.",
            )
        )
        db_session.commit()

        pipeline_module.generate_episode(db_session)

        llm_prompt = mock_llm["calls"][-1]["user"]
        assert "The kind of grey that never quite commits to rain." in llm_prompt
        assert "WEATHER REMARKS ALREADY USED" in llm_prompt

    def test_weather_angle_advances_with_each_banked_remark(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json):
        from app.sources.weather import WEATHER_ANGLES

        mock_llm["_state"]["response"] = json.loads(make_episode_json(
            weather_comment="A remark worth banking.",
        ))
        pipeline_module.generate_episode(db_session)
        assert WEATHER_ANGLES[0] in mock_llm["calls"][-1]["user"]

        mock_llm["_state"]["response"] = json.loads(make_episode_json(
            weather_comment="A different remark.",
        ))
        pipeline_module.generate_episode(db_session)
        assert WEATHER_ANGLES[1] in mock_llm["calls"][-1]["user"]

    def test_weather_comment_not_stored_without_weather(self, db_session, settings, mock_pipeline_env, mock_llm, make_episode_json, monkeypatch):
        """No forecast today, so a remark the model invented anyway must not be banked."""

        gather = pipeline_module._gather_source_data

        def gather_without_weather(**kwargs):
            result = gather(**kwargs)
            return dataclasses.replace(result, weather_text="", weather_summary=None)

        monkeypatch.setattr(pipeline_module, "_gather_source_data", gather_without_weather)
        mock_llm["_state"]["response"] = json.loads(make_episode_json(
            weather_comment="A stray remark about nothing.",
        ))

        episode = pipeline_module.generate_episode(db_session)

        assert episode.weather_summary == ""
        assert episode.weather_comment == ""


class TestPipelineFailures:
    def test_llm_error_marks_episode_failed(self, db_session, settings, mock_pipeline_env, monkeypatch, make_episode_json):
        from app import llm as llm_module
        from app.llm_providers import LlmProviderError

        def failing_chat(*, provider_config, system, user, temperature, **kwargs):
            raise LlmProviderError("OpenAI is down")

        monkeypatch.setattr(llm_module, "_chat_completion", failing_chat)
        monkeypatch.setattr("app.llm_providers.chat_completion", failing_chat)

        with pytest.raises(pipeline_module.PipelineError, match="OpenAI is down"):
            pipeline_module.generate_episode(db_session)

        episode = db_session.exec(select(Episode)).first()
        assert episode.status == EpisodeStatus.failed
        assert episode.title == "Generation failed"
        assert "OpenAI is down" in episode.error

    def test_tts_error_marks_episode_failed(self, db_session, settings, mock_pipeline_env, monkeypatch):
        from app.tts.base import TtsError

        class FailingTts:
            lists_full_catalog = True
            def synthesize(self, *args, **kwargs):
                raise TtsError("TTS provider unavailable")
            def list_voices(self):
                return []
            def get_voice(self, voice_id):
                return None

        monkeypatch.setattr(pipeline_module, "get_provider", lambda *, credentials, settings_provider: FailingTts())

        with pytest.raises(pipeline_module.PipelineError, match="TTS provider unavailable"):
            pipeline_module.generate_episode(db_session)

        episode = db_session.exec(select(Episode)).first()
        assert episode.status == EpisodeStatus.failed

    def test_audio_error_marks_episode_failed(self, db_session, settings, mock_pipeline_env, monkeypatch):
        from app.audio import AudioError

        def failing_assemble(*args, **kwargs):
            raise AudioError("ffmpeg failed to assemble the episode")

        monkeypatch.setattr(pipeline_module, "assemble_episode", failing_assemble)

        with pytest.raises(pipeline_module.PipelineError, match="ffmpeg failed"):
            pipeline_module.generate_episode(db_session)

        episode = db_session.exec(select(Episode)).first()
        assert episode.status == EpisodeStatus.failed
        assert episode.title == "Generation failed"

    def test_failure_records_audit_log_entry(self, db_session, settings, mock_pipeline_env, monkeypatch):
        from app import llm as llm_module
        from app.llm_providers import LlmProviderError

        def failing_chat(**kwargs):
            raise LlmProviderError("LLM exploded")

        monkeypatch.setattr(llm_module, "_chat_completion", failing_chat)
        monkeypatch.setattr("app.llm_providers.chat_completion", failing_chat)

        try:
            pipeline_module.generate_episode(db_session)
        except pipeline_module.PipelineError:
            pass

        episode = db_session.exec(select(Episode)).first()
        entries = db_session.exec(
            select(EpisodeLogEntry).where(EpisodeLogEntry.episode_id == episode.id)
        ).all()
        error_entries = [e for e in entries if e.status == "error"]
        assert len(error_entries) >= 1
        assert any("LLM exploded" in e.summary for e in error_entries)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestPipelineHelpers:
    def test_calendar_sources_skips_disabled_and_blank_feeds(self, db_session):
        from app.pipeline import _calendar_sources

        db_session.add(CalendarFeed(url="https://work.example/cal.ics", label="Work"))
        db_session.add(CalendarFeed(url="https://home.example/cal.ics", label="Home", enabled=False))
        db_session.add(CalendarFeed(url="   ", label="Empty"))
        db_session.commit()

        sources = _calendar_sources(db_session)
        assert [(source.label, source.url) for source in sources] == [
            ("Work", "https://work.example/cal.ics")
        ]

    def test_aired_story_keys_collects_urls_and_titles(self, db_session):
        from app.pipeline import _aired_story_keys

        episode = Episode(title="Old")
        db_session.add(episode)
        db_session.commit()
        db_session.refresh(episode)

        db_session.add(EpisodeArticle(episode_id=episode.id, title="Old Story", url="https://example.com/old"))
        db_session.commit()

        urls, titles = _aired_story_keys(db_session)
        assert "https://example.com/old" in urls
        assert "old story" in titles

    def test_excluded_topics_returns_all(self, db_session):
        from app.db import Preference
        from app.pipeline import _excluded_topics

        db_session.add(Preference(topic="politics"))
        db_session.add(Preference(topic="war"))
        db_session.commit()

        topics = _excluded_topics(db_session)
        assert set(topics) == {"politics", "war"}

    def test_covered_report_items_dedupes_case_insensitively(self, db_session):
        from app.pipeline import _covered_report_items

        episode = Episode(title="E1")
        db_session.add(episode)
        db_session.commit()
        db_session.refresh(episode)

        for item in ["Project Hail Mary", "project hail mary", "Dune"]:
            db_session.add(ReportedItem(report_type="books", item=item, episode_id=episode.id))
        db_session.commit()

        covered = _covered_report_items(db_session, "books")
        # Only one casing of the duplicate should survive, plus Dune.
        assert len(covered) == 2
        assert "Dune" in covered
        casefold_items = [r.casefold() for r in covered]
        assert casefold_items.count("project hail mary") == 1

    def test_covered_report_items_returns_full_history(self, db_session):
        from app.pipeline import _covered_report_items

        episode = Episode(title="E1")
        db_session.add(episode)
        db_session.commit()
        db_session.refresh(episode)

        for i in range(40):
            db_session.add(ReportedItem(report_type="true_story", item=f"Story {i}", episode_id=episode.id))
        db_session.commit()

        covered = _covered_report_items(db_session, "true_story")
        assert len(covered) == 40

    def test_covered_report_items_respects_limit(self, db_session):
        from app.pipeline import _covered_report_items

        episode = Episode(title="E1")
        db_session.add(episode)
        db_session.commit()
        db_session.refresh(episode)

        for i in range(10):
            db_session.add(ReportedItem(report_type="books", item=f"Book {i}", episode_id=episode.id))
        db_session.commit()

        covered = _covered_report_items(db_session, "books", limit=3)
        assert len(covered) == 3

    def test_variety_axis_rotates_with_coverage(self):
        from app.pipeline import _pick_variety_axis
        from app.report_types import get_report_type

        axes = get_report_type("true_story").variety_axes
        picked = [_pick_variety_axis("true_story", count) for count in range(len(axes))]
        assert len(set(picked)) == len(axes)

    def test_variety_axis_empty_for_report_type_without_axes(self):
        from app.pipeline import _pick_variety_axis

        assert _pick_variety_axis("books", 0) == ""

    def test_covered_item_count_includes_duplicates(self, db_session):
        from app.pipeline import _covered_item_count

        episode = Episode(title="E1")
        db_session.add(episode)
        db_session.commit()
        db_session.refresh(episode)

        for item in ["Story A", "story a", "Story B"]:
            db_session.add(ReportedItem(report_type="true_story", item=item, episode_id=episode.id))
        db_session.add(ReportedItem(report_type="books", item="Dune", episode_id=episode.id))
        db_session.commit()

        assert _covered_item_count(db_session, "true_story") == 3
        assert _covered_item_count(db_session, "books") == 1

    def test_past_market_comments_are_newest_first_and_deduped(self, db_session):
        from app.pipeline import _past_market_comments

        for title, comment in [
            ("E1", "Flat day."),
            ("E2", ""),
            ("E3", "flat day."),
            ("E4", "Green across the board."),
        ]:
            db_session.add(Episode(title=title, market_comment=comment))
            db_session.commit()

        comments = _past_market_comments(db_session)

        assert comments == ["Green across the board.", "flat day."]

    def test_past_market_comments_respects_limit(self, db_session):
        from app.pipeline import _past_market_comments

        for index in range(10):
            db_session.add(Episode(title=f"E{index}", market_comment=f"Aside {index}."))
        db_session.commit()

        assert len(_past_market_comments(db_session, limit=4)) == 4

    def test_past_weather_comments_are_newest_first_and_deduped(self, db_session):
        from app.pipeline import _past_weather_comments

        for title, comment in [
            ("E1", "Grey all day."),
            ("E2", ""),
            ("E3", "grey all day."),
            ("E4", "Windows open weather."),
        ]:
            db_session.add(Episode(title=title, weather_comment=comment))
            db_session.commit()

        comments = _past_weather_comments(db_session)

        assert comments == ["Windows open weather.", "grey all day."]

    def test_past_weather_comments_respects_limit(self, db_session):
        from app.pipeline import _past_weather_comments

        for index in range(10):
            db_session.add(Episode(title=f"E{index}", weather_comment=f"Remark {index}."))
        db_session.commit()

        assert len(_past_weather_comments(db_session, limit=4)) == 4

    def test_weather_angle_steps_through_every_framing(self):
        from app.sources.weather import WEATHER_ANGLES, pick_weather_angle

        drawn = [pick_weather_angle(index) for index in range(len(WEATHER_ANGLES))]

        assert len(set(drawn)) == len(WEATHER_ANGLES)
        assert pick_weather_angle(len(WEATHER_ANGLES)) == WEATHER_ANGLES[0]

    def test_resolve_special_report_returns_none_when_not_configured(self, db_session):
        from app.pipeline import _resolve_special_report

        now = datetime.now(timezone.utc)
        assert _resolve_special_report(db_session, now) is None

    def test_resolve_special_report_returns_report_when_configured(self, db_session):
        from app.pipeline import _resolve_special_report

        now = datetime.now(timezone.utc)
        db_session.add(WeeklyReport(day_of_week=now.weekday(), report_type="books", user_input="sci-fi"))
        db_session.commit()

        report = _resolve_special_report(db_session, now)
        assert report is not None
        assert report.report_type_id == "books"
        assert report.user_input == "sci-fi"
