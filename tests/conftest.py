"""Shared pytest fixtures for the Morning News pipeline tests.

Every test runs against an in-memory SQLite database (fresh per test) with all
external API calls mocked at module boundaries: news gathering, weather, stocks,
calendar, LLM completions, TTS synthesis, ffmpeg audio assembly, and the health
report refresh. No network, no ffmpeg, no real AI provider is ever invoked.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app import audio as audio_module
from app import llm as llm_module
from app import llm_providers
from app import pipeline as pipeline_module
from app import pipeline
from app.credentials import Credentials
from app.episode_log import EpisodeAuditLog
from app.sources import calendar as calendar_module
from app.sources import news as news_module
from app.sources import stocks as stocks_module
from app.sources import weather as weather_module
from app.tts.base import TtsVoice
from app.tts.providers import TtsProviderId
from app.tts.voice_selection import ResolvedVoice


# ---------------------------------------------------------------------------
# Database / settings fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session(monkeypatch):
    """Yield a Session backed by a fresh in-memory SQLite database."""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)

    # Patch the engine in every module that imported it directly by value.
    import app.db as db_module
    monkeypatch.setattr(pipeline_module, "engine", engine)
    monkeypatch.setattr(db_module, "engine", engine)
    # Settings.default_factory-style code paths sometimes reference engine via
    # the db module directly; already covered above.

    with Session(engine) as session:
        yield session


@pytest.fixture()
def settings(db_session):
    """Return the singleton Settings row with sensible test defaults."""

    from app.db import Settings, get_settings

    settings = get_settings(db_session)
    settings.podcast_title = "Morning News"
    settings.podcast_author = "Test Host"
    settings.podcast_description = "A test briefing."
    settings.timezone = "UTC"
    settings.locality = "Testville"
    settings.latitude = 0.0
    settings.longitude = 0.0
    settings.weather_enabled = True
    settings.stocks_enabled = False
    settings.calendar_url = ""
    settings.target_minutes_min = 1.5
    settings.target_minutes_max = 3.0
    settings.llm_provider = "openai"
    settings.llm_model = "gpt-4o-mini"
    settings.tts_provider = "elevenlabs"
    settings.voice_id = "test-voice"
    settings.voice_model = "eleven_v3"
    settings.intro_enabled = False
    settings.outro_enabled = False
    settings.news_hl = "en-US"
    settings.news_gl = "US"
    settings.news_ceid = "US:en"
    settings.admin1 = ""
    settings.country = ""
    settings.max_article_length = 6000
    db_session.add(settings)
    db_session.commit()
    db_session.refresh(settings)
    return settings


@pytest.fixture()
def credentials():
    """Return Credentials with a test OpenAI key so provider resolution works."""

    return Credentials(
        openai_api_key="test-key",
        openai_stored=True,
    )


@pytest.fixture()
def mock_credentials(monkeypatch, credentials):
    """Make pipeline.load_credentials return the test credentials."""

    monkeypatch.setattr(pipeline_module, "load_credentials", lambda settings: credentials)
    return credentials


# ---------------------------------------------------------------------------
# Mock external dependencies
# ---------------------------------------------------------------------------


class StubTtsProvider:
    """A TTS provider that writes a tiny mp3 file instead of calling an API."""

    lists_full_catalog = True

    def synthesize(self, text, output_path, *, voice_id, model_id, emotion=""):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ID3\x03fake-mp3-audio-data")
        return output_path

    def list_voices(self):
        return [TtsVoice(voice_id="test-voice", name="Test Host", language="en", accent="american")]

    def get_voice(self, voice_id):
        for voice in self.list_voices():
            if voice.voice_id == voice_id:
                return voice
        return None


@pytest.fixture()
def mock_tts(monkeypatch):
    """Replace TTS provider resolution and audio assembly with no-op stubs."""

    stub = StubTtsProvider()

    monkeypatch.setattr(pipeline_module, "get_provider", lambda *, credentials, settings_provider: stub)
    monkeypatch.setattr(pipeline_module, "resolve_tts_provider", lambda *, credentials, settings_provider: TtsProviderId.elevenlabs)
    monkeypatch.setattr(pipeline_module, "normalize_voice_model", lambda provider_id, model: model or "eleven_v3")
    monkeypatch.setattr(
        pipeline_module,
        "resolve_episode_voice",
        lambda provider, *, voice_id, voice_randomize, voice_language, voice_accent, news_hl, date_text: ResolvedVoice(
            voice_id=voice_id, name="Test Host"
        ),
    )
    # Skip ffmpeg: don't touch real audio files, just ensure the output exists.
    monkeypatch.setattr(pipeline_module, "speed_up_narration", lambda voice_path: voice_path)
    monkeypatch.setattr(pipeline_module, "assemble_episode", lambda voice_mp3, output_mp3, *args, **kwargs: _write_stub_mp3(output_mp3))
    monkeypatch.setattr(pipeline_module, "probe_duration", lambda path: 60.0)
    return stub


def _write_stub_mp3(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ID3\x03fake-final-mp3")
    return path


@pytest.fixture()
def mock_health(monkeypatch):
    """Prevent health checks from running."""

    monkeypatch.setattr(pipeline_module, "refresh_health_report", lambda *args, **kwargs: None)


@pytest.fixture()
def mock_news(monkeypatch):
    """Replace news.gather_articles with a stub that returns fixed articles."""

    from app.sources.news import Article

    articles = [
        Article(
            title="City council approves new park",
            url="https://example.com/park",
            publisher="Test Gazette",
            summary="The council approved a new park downtown.",
            body="The city council approved a new park downtown. The project will break ground next month.",
            source_name="Test Gazette",
            priority=False,
        ),
        Article(
            title="Tech company announces expansion",
            url="https://example.com/tech",
            publisher="Tech Daily",
            summary="A local tech company is expanding.",
            body="A local tech company announced a major expansion that will create 200 jobs.",
            source_name="Tech Daily",
            priority=False,
        ),
    ]

    def stub_gather(sources, *, zyte_api_key=None, exclude_urls=None, exclude_titles=None, **kwargs):
        return list(articles)

    monkeypatch.setattr(news_module, "gather_articles", stub_gather)
    monkeypatch.setattr(pipeline_module, "_gather_source_data", _stub_gather_source_data)
    return articles


def _stub_gather_source_data(*, settings, credentials, sources, stock_symbols, aired_urls=None, aired_titles=None):
    """Replacement for pipeline._gather_source_data that avoids all network I/O."""

    from app.pipeline import _SourceGatherResult
    from app.sources.weather import WeatherSummary

    articles = news_module.gather_articles(
        sources,
        zyte_api_key=credentials.zyte_api_key,
        exclude_urls=aired_urls,
        exclude_titles=aired_titles,
    )

    weather_text = "clear sky, a high of 20 and a low of 10"
    weather_summary = WeatherSummary(text="clear sky", temperature_max=20.0, temperature_min=10.0)

    market_text = ""
    market_reaction = ""
    if settings.stocks_enabled and stock_symbols:
        from app.sources import stocks as stocks_module
        summary = stocks_module.get_market_summary(
            stock_symbols,
            credentials=credentials,
            mature_reactions=settings.stocks_mature_reactions,
        )
        if summary is not None:
            market_text = summary.text
            market_reaction = summary.reaction_hint

    return _SourceGatherResult(
        articles=articles,
        weather_text=weather_text,
        weather_summary=weather_summary,
        market_text=market_text,
        market_reaction=market_reaction,
        events=[],
    )


@pytest.fixture()
def mock_weather(monkeypatch):
    """Stub weather resolution so no network calls are made."""

    from app.sources.weather import WeatherSummary

    def stub_get_weather(lat, lon, tz="auto", *, provider="", weatherapi_api_key=None):
        return WeatherSummary(text="sunny, a high of 22 and a low of 11", temperature_max=22.0, temperature_min=11.0)

    monkeypatch.setattr(weather_module, "get_weather", stub_get_weather)
    monkeypatch.setattr(weather_module, "resolve_location", lambda **kwargs: None)


@pytest.fixture()
def mock_stocks(monkeypatch):
    from app.sources.stocks import MarketSummary

    def stub_get_market_summary(symbols, *, credentials, mature_reactions=False):
        return MarketSummary(text="Mostly up - 3 of 4 holdings rose.", reaction_hint="a good morning")

    monkeypatch.setattr(stocks_module, "get_market_summary", stub_get_market_summary)


@pytest.fixture()
def mock_calendar(monkeypatch):
    monkeypatch.setattr(calendar_module, "fetch_events", lambda url, tz="UTC": [])


@pytest.fixture()
def mock_llm(monkeypatch):
    """Stub LLM chat completion to return a valid episode-content JSON."""

    state: dict[str, Any] = {
        "response": {
            "title": "Morning News for Today",
            "description": "Your daily briefing.",
            "script": "Good morning. Here is your briefing. The weather is sunny today. In local news, the city council approved a new park. That is all for now.",
            "used_article_ids": [0],
            "used_message_ids": [],
            "reported_items": [],
            "reported_links": [],
        }
    }
    calls: list[dict[str, Any]] = []

    def stub_chat_completion(*, provider_config, system, user, temperature, response_schema=None, response_schema_name="response", json_mode=False):
        calls.append({"system": system, "user": user, "temperature": temperature})
        return json.dumps(state["response"])

    monkeypatch.setattr(llm_module, "_chat_completion", stub_chat_completion)
    monkeypatch.setattr(llm_providers, "chat_completion", stub_chat_completion)
    monkeypatch.setattr(llm_module, "summarize_article", lambda text, target_chars, **kwargs: text[:target_chars])

    return {"default_response": state["response"], "_state": state, "calls": calls}


@pytest.fixture()
def mock_pipeline_env(mock_tts, mock_health, mock_news, mock_weather, mock_stocks, mock_calendar, mock_llm, mock_credentials):
    """Bundle all external-dependency mocks into one fixture for pipeline tests."""

    return {
        "tts": mock_tts,
        "news": mock_news,
        "weather": mock_weather,
        "stocks": mock_stocks,
        "calendar": mock_calendar,
        "llm": mock_llm,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def make_episode_json():
    """Return a function that builds a valid LLM JSON response."""

    def _make(**overrides):
        base = {
            "title": "Test Episode",
            "description": "A test episode.",
            "script": "Hello, this is your morning briefing. The weather is fine. That is all.",
            "used_article_ids": [],
            "used_message_ids": [],
            "reported_items": [],
            "reported_links": [],
        }
        base.update(overrides)
        return json.dumps(base)

    return _make
