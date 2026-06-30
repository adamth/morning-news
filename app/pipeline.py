"""Daily episode generation pipeline."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from . import llm
from .audio import assemble_episode, probe_duration, speed_up_narration
from .config import config
from .db import (
    Episode,
    EpisodeArticle,
    EpisodeStatus,
    Message,
    MessageStatus,
    Settings,
    Source,
    User,
    WatchlistItem,
    engine,
    get_settings,
    utcnow,
)
from .news_categories import format_priorities, parse_selected
from .sources import news, weather
from .sources.calendar import fetch_events
from .sources import stocks
from .health import refresh_health_report
from .tts import build_narrator_opening, get_provider, resolve_episode_voice

logger = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    pass


def generate_episode(session: Session) -> Episode:
    """Run the full generation flow and return the finished Episode."""

    settings = get_settings(session)
    timezone = _safe_zone(settings.timezone)
    now_local = datetime.now(timezone)

    episode = Episode(
        title="Generating\u2026",
        status=EpisodeStatus.generating,
        created_at=utcnow(),
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)

    try:
        _run(session, settings, episode, timezone, now_local)
    except Exception as error:
        logger.exception("Episode generation failed")
        episode.status = EpisodeStatus.failed
        episode.error = str(error)
        episode.title = "Generation failed"
        session.add(episode)
        session.commit()
        try:
            refresh_health_report(force_all=True)
        except Exception:
            logger.exception("Health check refresh after episode failure failed")
        raise PipelineError(str(error)) from error

    return episode


def _run(
    session: Session,
    settings: Settings,
    episode: Episode,
    timezone: ZoneInfo,
    now_local: datetime,
) -> None:
    date_text = now_local.strftime("%A, %B %d, %Y")

    # 1. Gather news.
    sources = _news_sources(session, settings)
    articles = news.gather_articles(sources)
    logger.info("Gathered %d candidate articles", len(articles))

    # 2. Weather.
    weather_text = ""
    if settings.weather_enabled and settings.latitude is not None and settings.longitude is not None:
        summary = weather.get_weather(settings.latitude, settings.longitude, settings.timezone)
        if summary:
            weather_text = summary.text

    # 2b. Stock watchlist (aggregate performance only).
    market_text = ""
    market_reaction = ""
    if settings.stocks_enabled:
        symbols = [
            item.symbol
            for item in session.exec(
                select(WatchlistItem).where(WatchlistItem.enabled == True)  # noqa: E712
            ).all()
        ]
        if symbols:
            summary = stocks.get_market_summary(
                symbols,
                mature_reactions=settings.stocks_mature_reactions,
            )
            if summary:
                market_text = summary.text
                market_reaction = summary.reaction_hint

    # 3. Calendar events.
    events = fetch_events(settings.calendar_url, settings.timezone)
    events_text = [event.describe(timezone) for event in events]

    # 4. Pending private messages (all users).
    messages = session.exec(
        select(Message).where(Message.status == MessageStatus.pending)
    ).all()

    # 5. Summarize over-long articles to control token cost.
    _summarize_long_articles(articles, settings)

    article_inputs = [
        llm.ArticleInput(
            id=index,
            title=item.title,
            publisher=item.publisher,
            content=item.content,
            source_name=item.source_name,
        )
        for index, item in enumerate(articles)
        if item.content
    ]
    message_inputs = [llm.MessageInput(id=msg.id, text=msg.text) for msg in messages]
    excluded_topics = _excluded_topics(session)

    # 6. Generate the script.
    content = llm.generate_episode(
        model=settings.openrouter_model,
        podcast_title=settings.podcast_title,
        date_text=date_text,
        locality=settings.locality,
        target_min=settings.target_minutes_min,
        target_max=settings.target_minutes_max,
        priorities_text=format_priorities(parse_selected(settings.preferred_categories)),
        excluded_topics=excluded_topics,
        weather_text=weather_text,
        market_text=market_text,
        market_reaction=market_reaction,
        events=events_text,
        messages=message_inputs,
        articles=article_inputs,
    )

    # 7. Persist show-note articles.
    used_articles = [articles[i] for i in content.used_article_ids if 0 <= i < len(articles)]
    for used in used_articles:
        session.add(
            EpisodeArticle(
                episode_id=episode.id,
                title=used.title,
                publisher=used.publisher,
                url=used.url,
            )
        )

    # 8. Resolve included private messages (each used exactly once).
    used_message_ids = set(content.used_message_ids)
    for message in messages:
        if message.id in used_message_ids:
            message.status = MessageStatus.resolved
            message.episode_id = episode.id
            message.resolved_at = utcnow()
            session.add(message)

    # 9. Synthesize speech.
    voice_path = config.episodes_dir / f"{episode.id}.voice.mp3"
    final_path = config.episodes_dir / f"{episode.id}.mp3"
    provider = get_provider()
    resolved_voice = resolve_episode_voice(
        provider,
        voice_id=settings.voice_id,
        voice_randomize=settings.voice_randomize,
        voice_language=settings.voice_language,
        voice_accent=settings.voice_accent,
        news_hl=settings.news_hl,
        date_text=date_text,
    )
    narrator_opening = build_narrator_opening(resolved_voice.name, settings.podcast_title)
    narration_text = f"{narrator_opening}\n\n{content.script}"
    provider.synthesize(
        narration_text,
        voice_path,
        voice_id=resolved_voice.voice_id,
        model_id=settings.voice_model,
    )
    speed_up_narration(voice_path)

    # 10. Assemble with intro/outro music + normalize.
    intro = config.intro_path if (settings.intro_enabled and config.intro_path.exists()) else None
    outro = config.outro_path if (settings.outro_enabled and config.outro_path.exists()) else None
    assemble_episode(
        voice_path,
        final_path,
        intro,
        intro_play_seconds=settings.intro_play_seconds,
        outro_mp3=outro,
        outro_play_seconds=settings.outro_play_seconds,
    )
    voice_path.unlink(missing_ok=True)

    # 11. Finalize episode metadata.
    episode.title = content.title
    episode.description = content.description
    episode.script = content.script
    episode.audio_path = final_path.name
    episode.duration_seconds = probe_duration(final_path)
    episode.weather_summary = weather_text
    episode.events_summary = "; ".join(events_text)
    episode.market_summary = market_text
    episode.status = EpisodeStatus.ready
    session.add(episode)
    session.commit()
    session.refresh(episode)
    logger.info("Episode %s ready: %s", episode.id, episode.title)


def _news_sources(session: Session, settings: Settings) -> list[news.NewsSource]:
    sources: list[news.NewsSource] = []

    for source in session.exec(select(Source).where(Source.enabled == True)).all():  # noqa: E712
        sources.append(news.NewsSource(url=source.url, name=source.name or source.url))

    admin1 = settings.admin1
    country = settings.country
    if settings.locality and (not admin1 or not country):
        resolved = weather.resolve_location(
            locality=settings.locality,
            latitude=settings.latitude,
            longitude=settings.longitude,
            country_code=settings.news_gl,
        )
        if resolved is not None:
            admin1 = admin1 or resolved.admin1
            country = country or resolved.country

    if settings.locality:
        sources.extend(
            news.build_local_news_sources(
                locality=settings.locality,
                admin1=admin1,
                country=country,
                hl=settings.news_hl,
                gl=settings.news_gl,
                ceid=settings.news_ceid,
            )
        )

    return sources


def _excluded_topics(session: Session) -> list[str]:
    from .db import Preference

    return [pref.topic for pref in session.exec(select(Preference)).all()]


def _summarize_long_articles(articles: list[news.Article], settings: Settings) -> None:
    limit = settings.max_article_length
    for article in articles:
        body = article.body
        if body and len(body) > limit:
            try:
                article.body = llm.summarize_article(body, limit, settings.openrouter_model)
            except llm.LLMError as error:
                logger.warning("Summarization failed, truncating instead: %s", error)
                article.body = body[:limit]


def _safe_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def generate_episode_background() -> None:
    """Entry point for the scheduler: open its own session."""

    with Session(engine) as session:
        try:
            generate_episode(session)
        except PipelineError:
            pass  # already logged and persisted as a failed episode
