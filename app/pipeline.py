"""Daily episode generation pipeline."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from . import llm
from .audio import assemble_episode, probe_duration, speed_up_narration
from .config import config
from .credentials import Credentials, load_credentials
from .db import (
    CalendarFeed,
    Episode,
    EpisodeArticle,
    EpisodeStatus,
    Message,
    MessageStatus,
    ReportedItem,
    Settings,
    Source,
    User,
    WatchlistItem,
    engine,
    get_settings,
    utcnow,
)
from .news_categories import format_priorities, parse_selected
from .report_types import REPORT_TYPES, WEEKDAY_LABELS, get_report_type, is_special
from .sources import news, weather
from .sources.calendar import CalendarEvent, CalendarSource, fetch_all_events
from .sources.weather import WeatherSummary
from .sources import stocks
from .episode_log import LogTimer, active_log, episode_audit_log
from .health import refresh_health_report
from .templating import format_spoken_date
from .tts import (
    TTS_PROVIDER_LABELS,
    TtsProviderId,
    build_narrator_opening,
    get_provider,
    normalize_voice_model,
    resolve_episode_voice,
    resolve_tts_provider,
)

logger = logging.getLogger(__name__)

COVERED_ITEMS_PROMPT_LIMIT = 750
"""Cap on the exclusion list sent to the LLM — years of daily episodes, then it forgets."""

MARKET_COMMENTS_PROMPT_LIMIT = 180
"""Cap on the past market asides sent to the LLM — well over half a year of trading days."""


class PipelineError(RuntimeError):
    pass


@dataclass
class _SourceGatherResult:
    articles: list[news.Article]
    weather_text: str
    weather_summary: WeatherSummary | None
    market_text: str
    market_reaction: str
    events: list[CalendarEvent]


def generate_episode(session: Session) -> Episode:
    """Run the full generation flow and return the finished Episode."""

    settings = get_settings(session)
    credentials = load_credentials(settings)
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
        with episode_audit_log(session, episode.id) as audit:
            audit.record(
                "pipeline",
                "Start generation",
                summary=f"Generating episode for {format_spoken_date(now_local)}",
                request={
                    "timezone": settings.timezone,
                    "locality": settings.locality,
                    "weather_enabled": settings.weather_enabled,
                    "stocks_enabled": settings.stocks_enabled,
                    "calendars": [
                        source.label or source.url for source in _calendar_sources(session)
                    ],
                    "llm_provider": settings.llm_provider or "(auto)",
                    "llm_model": settings.llm_model,
                    "target_minutes": [settings.target_minutes_min, settings.target_minutes_max],
                },
            )
            try:
                _run(session, settings, credentials, episode, timezone, now_local)
            except Exception as error:
                audit.record(
                    "pipeline",
                    "Generation failed",
                    status="error",
                    summary=str(error),
                    response={"error": str(error)},
                )
                raise
            finally:
                audit.flush()
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
    credentials: Credentials,
    episode: Episode,
    timezone: ZoneInfo,
    now_local: datetime,
) -> None:
    date_text = format_spoken_date(now_local)

    # 1. Gather news, weather, stocks, and calendar in parallel.
    sources = _news_sources(session, settings)
    calendar_sources = _calendar_sources(session)
    audit = active_log()
    if audit is not None:
        audit.record(
            "news",
            "Configure news sources",
            summary=f"{len(sources)} feed(s) configured",
            response=[
                {
                    "name": source.name,
                    "url": source.url,
                    "google_news": source.is_google_news,
                    "priority": source.priority,
                }
                for source in sources
            ],
        )

    stock_symbols: list[str] = []
    if settings.stocks_enabled:
        stock_symbols = [
            item.symbol
            for item in session.exec(
                select(WatchlistItem).where(WatchlistItem.enabled == True)  # noqa: E712
            ).all()
        ]

    aired_urls, aired_titles = _aired_story_keys(session)

    gather_timer = LogTimer.start()
    gathered = _gather_source_data(
        settings=settings,
        credentials=credentials,
        sources=sources,
        calendar_sources=calendar_sources,
        stock_symbols=stock_symbols,
        aired_urls=aired_urls,
        aired_titles=aired_titles,
    )
    logger.info("Gathered %d candidate articles", len(gathered.articles))
    if audit is not None:
        audit.record(
            "news",
            "Gather articles",
            summary=f"{len(gathered.articles)} candidate article(s) collected",
            response={
                "count": len(gathered.articles),
                "articles": [
                    {
                        "title": article.title,
                        "publisher": article.publisher,
                        "url": article.url,
                        "source": article.source_name,
                        "content_chars": len(article.content),
                    }
                    for article in gathered.articles
                ],
            },
            duration_ms=gather_timer.elapsed_ms(),
        )
        if settings.weather_enabled and settings.latitude is not None and settings.longitude is not None:
            audit.record(
                "weather",
                "Fetch forecast",
                status="success" if gathered.weather_text else "skipped",
                summary=gathered.weather_text or "Weather unavailable",
                request={
                    "latitude": settings.latitude,
                    "longitude": settings.longitude,
                    "timezone": settings.timezone,
                },
                response={
                    "text": gathered.weather_text or None,
                    "temperature_max": (
                        gathered.weather_summary.temperature_max if gathered.weather_summary else None
                    ),
                    "temperature_min": (
                        gathered.weather_summary.temperature_min if gathered.weather_summary else None
                    ),
                },
            )
        else:
            audit.record(
                "weather",
                "Fetch forecast",
                status="skipped",
                summary="Weather disabled or location not set",
            )

        if settings.stocks_enabled:
            if stock_symbols:
                audit.record(
                    "stocks",
                    "Fetch watchlist quotes",
                    status="success" if gathered.market_text else "error",
                    summary=gathered.market_text or "No quotes returned",
                    request={"symbols": stock_symbols, "mature_reactions": settings.stocks_mature_reactions},
                    response={
                        "text": gathered.market_text or None,
                        "reaction_hint": gathered.market_reaction or None,
                    },
                )
            else:
                audit.record("stocks", "Fetch watchlist quotes", status="skipped", summary="Watchlist empty")
        else:
            audit.record("stocks", "Fetch watchlist quotes", status="skipped", summary="Stocks disabled")

        events_text = [event.describe(timezone) for event in gathered.events]
        audit.record(
            "calendar",
            "Fetch today's events",
            status="success" if calendar_sources else "skipped",
            summary=(
                f"{len(events_text)} event(s) today across {len(calendar_sources)} calendar(s)"
                if calendar_sources
                else "No calendars added"
            ),
            request={
                "calendars": [
                    {"label": source.label, "url": source.url} for source in calendar_sources
                ],
                "timezone": settings.timezone,
            },
            response={"events": events_text},
        )

    articles = gathered.articles
    weather_text = gathered.weather_text
    market_text = gathered.market_text
    market_reaction = gathered.market_reaction
    events_text = [event.describe(timezone) for event in gathered.events]

    # 2. Pending private messages (all users).
    messages = session.exec(
        select(Message).where(Message.status == MessageStatus.pending)
    ).all()
    if audit is not None:
        audit.record(
            "messages",
            "Load pending messages",
            summary=f"{len(messages)} pending message(s)",
            response=[{"id": message.id, "text": message.text} for message in messages],
        )

    # 5. Summarize over-long articles to control token cost.
    _summarize_long_articles(articles, settings, credentials)

    article_inputs = [
        llm.ArticleInput(
            id=index,
            title=item.title,
            publisher=item.publisher,
            content=item.content,
            source_name=item.source_name,
            priority=item.priority,
        )
        for index, item in enumerate(articles)
        if item.content
    ]
    message_inputs = [llm.MessageInput(id=msg.id, text=msg.text) for msg in messages]
    excluded_topics = _excluded_topics(session)

    # 6. Generate the script.
    timer = LogTimer.start()
    special_report = _resolve_special_report(session, now_local)
    if special_report is not None:
        special_report.covered_items = _covered_report_items(
            session, special_report.report_type_id
        )
        special_report.variety_axis = _pick_variety_axis(
            special_report.report_type_id, _covered_item_count(session, special_report.report_type_id)
        )
    if audit is not None and special_report is not None:
        audit.record(
            "pipeline",
            "Special report active",
            summary=f"{special_report.label} (weekday {now_local.weekday()} — {WEEKDAY_LABELS[now_local.weekday()]})",
            response={
                "report_type": special_report.report_type_id,
                "label": special_report.label,
                "user_input_chars": len(special_report.user_input),
                "user_input": special_report.user_input,
                "covered_items_count": len(special_report.covered_items),
                "covered_items": special_report.covered_items,
                "variety_axis": special_report.variety_axis,
            },
        )
    content = llm.generate_episode(
        credentials=credentials,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
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
        special_report=special_report,
        past_market_comments=_past_market_comments(session) if market_text else [],
    )
    if audit is not None:
        audit.record(
            "llm",
            "Write episode script",
            summary=f"Title: {content.title}",
            response={
                "title": content.title,
                "description": content.description,
                "script_chars": len(content.script),
                "used_article_ids": content.used_article_ids,
                "used_message_ids": content.used_message_ids,
                "reported_items": content.reported_items,
                "reported_links": [
                    {"title": link.title, "url": link.url}
                    for link in content.reported_links
                ],
                "market_comment": content.market_comment,
                "script": content.script,
            },
            duration_ms=timer.elapsed_ms(),
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

    # 7b. Remember what this special report covered so future ones don't repeat it.
    if special_report is not None:
        link_by_title: dict[str, str] = {
            link.title.strip().casefold(): link.url.strip()
            for link in content.reported_links
        }
        covered_titles: list[str] = list(content.reported_items)
        for link in content.reported_links:
            if link.title.strip() and link.title.strip() not in covered_titles:
                covered_titles.append(link.title.strip())
        # A silent model would otherwise leave no trace and be free to repeat itself.
        if not covered_titles and content.title.strip():
            covered_titles.append(content.title.strip())
        for title in covered_titles:
            url = link_by_title.get(title.strip().casefold(), "")
            session.add(
                ReportedItem(
                    report_type=special_report.report_type_id,
                    item=title,
                    url=url,
                    episode_id=episode.id,
                )
            )
        if audit is not None:
            audit.record(
                "pipeline",
                "Stored reported items",
                summary=f"{len(covered_titles)} item(s) saved for {special_report.report_type_id}",
                response={
                    "report_type": special_report.report_type_id,
                    "items": covered_titles,
                    "reported_links": [
                        {"title": link.title, "url": link.url}
                        for link in content.reported_links
                    ],
                },
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
    provider_id = resolve_tts_provider(
        credentials=credentials, settings_provider=settings.tts_provider
    )
    provider = get_provider(credentials=credentials, settings_provider=settings.tts_provider)
    voice_model = normalize_voice_model(provider_id, settings.voice_model)
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
    narration_text = f"{narrator_opening} {content.script}"
    timer = LogTimer.start()
    provider.synthesize(
        narration_text,
        voice_path,
        voice_id=resolved_voice.voice_id,
        model_id=voice_model,
        emotion=settings.speechify_emotion if provider_id is TtsProviderId.speechify else "",
    )
    if audit is not None:
        audit.record(
            "tts",
            "Synthesize narration",
            summary=f"{len(narration_text)} characters via {TTS_PROVIDER_LABELS[provider_id]}",
            request={
                "voice_id": resolved_voice.voice_id,
                "voice_name": resolved_voice.name,
                "model_id": voice_model,
                "emotion": settings.speechify_emotion if provider_id is TtsProviderId.speechify else "",
                "text_chars": len(narration_text),
                "text": narration_text,
            },
            response={"output_path": str(voice_path.name)},
            duration_ms=timer.elapsed_ms(),
        )
    speed_up_narration(voice_path)

    # 10. Assemble with intro/outro music + normalize.
    intro = config.intro_path if (settings.intro_enabled and config.intro_path.exists()) else None
    outro = config.outro_path if (settings.outro_enabled and config.outro_path.exists()) else None
    timer = LogTimer.start()
    assemble_episode(
        voice_path,
        final_path,
        intro,
        intro_play_seconds=settings.intro_play_seconds,
        outro_mp3=outro,
        outro_play_seconds=settings.outro_play_seconds,
    )
    if audit is not None:
        audit.record(
            "audio",
            "Assemble episode audio",
            summary="Mixed narration with intro/outro and normalized loudness",
            request={
                "intro": intro.name if intro else None,
                "intro_play_seconds": settings.intro_play_seconds,
                "outro": outro.name if outro else None,
                "outro_play_seconds": settings.outro_play_seconds,
                "narration_speed": "1.1x",
            },
            response={"output_path": final_path.name},
            duration_ms=timer.elapsed_ms(),
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
    episode.market_comment = content.market_comment if market_text else ""
    episode.status = EpisodeStatus.ready
    session.add(episode)
    session.commit()
    session.refresh(episode)
    if audit is not None:
        audit.record(
            "pipeline",
            "Complete generation",
            summary=f"Episode ready — {episode.duration_seconds and round(episode.duration_seconds / 60, 1)} min",
            response={
                "title": episode.title,
                "duration_seconds": episode.duration_seconds,
                "articles_used": len(used_articles),
                "messages_used": len(used_message_ids),
            },
        )
    logger.info("Episode %s ready: %s", episode.id, episode.title)


def _gather_source_data(
    *,
    settings: Settings,
    credentials: Credentials,
    sources: list[news.NewsSource],
    calendar_sources: list[CalendarSource],
    stock_symbols: list[str],
    aired_urls: set[str] | None = None,
    aired_titles: set[str] | None = None,
) -> _SourceGatherResult:
    """Fetch news, weather, stocks, and calendar concurrently."""

    tasks: dict[str, object] = {}

    def fetch_news() -> list[news.Article]:
        return news.gather_articles(
            sources,
            zyte_api_key=credentials.zyte_api_key,
            exclude_urls=aired_urls,
            exclude_titles=aired_titles,
        )

    def fetch_weather() -> tuple[str, WeatherSummary | None]:
        if (
            not settings.weather_enabled
            or settings.latitude is None
            or settings.longitude is None
        ):
            return "", None
        summary = weather.get_weather(
            settings.latitude,
            settings.longitude,
            settings.timezone,
            provider=settings.weather_provider,
            weatherapi_api_key=credentials.weatherapi_api_key,
        )
        return (summary.text, summary) if summary else ("", None)

    def fetch_stocks() -> tuple[str, str]:
        if not settings.stocks_enabled or not stock_symbols:
            return "", ""
        summary = stocks.get_market_summary(
            stock_symbols,
            credentials=credentials,
            mature_reactions=settings.stocks_mature_reactions,
        )
        if summary is None:
            return "", ""
        return summary.text, summary.reaction_hint

    def fetch_calendar() -> list[CalendarEvent]:
        return fetch_all_events(calendar_sources, settings.timezone)

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="gather") as executor:
        tasks["news"] = executor.submit(copy_context().run, fetch_news)
        tasks["weather"] = executor.submit(copy_context().run, fetch_weather)
        tasks["stocks"] = executor.submit(copy_context().run, fetch_stocks)
        tasks["calendar"] = executor.submit(copy_context().run, fetch_calendar)

        articles = tasks["news"].result()
        weather_text, weather_summary = tasks["weather"].result()
        market_text, market_reaction = tasks["stocks"].result()
        events = tasks["calendar"].result()

    return _SourceGatherResult(
        articles=articles,
        weather_text=weather_text,
        weather_summary=weather_summary,
        market_text=market_text,
        market_reaction=market_reaction,
        events=events,
    )


def _calendar_sources(session: Session) -> list[CalendarSource]:
    feeds = session.exec(
        select(CalendarFeed)
        .where(CalendarFeed.enabled == True)  # noqa: E712
        .order_by(CalendarFeed.created_at)
    ).all()
    return [CalendarSource(url=feed.url, label=feed.label) for feed in feeds if feed.url.strip()]


def _news_sources(session: Session, settings: Settings) -> list[news.NewsSource]:
    sources: list[news.NewsSource] = []

    for source in session.exec(select(Source).where(Source.enabled == True)).all():  # noqa: E712
        sources.append(
            news.NewsSource(
                url=source.url,
                name=source.name or source.url,
                priority=source.priority,
            )
        )

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


def _aired_story_keys(session: Session) -> tuple[set[str], set[str]]:
    """URLs and normalized titles of every article used in a past episode."""

    urls: set[str] = set()
    titles: set[str] = set()
    for row in session.exec(select(EpisodeArticle)).all():
        if row.url.strip():
            urls.add(row.url)
        title = row.title.strip().lower()
        if title:
            titles.add(title)
    return urls, titles


def _excluded_topics(session: Session) -> list[str]:
    from .db import Preference

    return [pref.topic for pref in session.exec(select(Preference)).all()]


def _resolve_special_report(session: Session, now_local: datetime) -> llm.SpecialReport | None:
    """Look up today's configured special report, if any."""

    from .db import WeeklyReport

    day_of_week = now_local.weekday()
    row = session.exec(
        select(WeeklyReport).where(WeeklyReport.day_of_week == day_of_week)
    ).first()
    if row is None or not is_special(row.report_type):
        return None
    report_type = get_report_type(row.report_type)
    if report_type is None:
        return None
    return llm.SpecialReport(
        report_type_id=report_type.id,
        label=report_type.label,
        prompt=report_type.prompt,
        user_input=row.user_input,
    )


def _covered_report_items(
    session: Session,
    report_type_id: str,
    *,
    limit: int = COVERED_ITEMS_PROMPT_LIMIT,
) -> list[str]:
    """Return every item this report type has ever covered, most-recent first.

    The whole history goes into the prompt as a hard exclusion list; `limit` is
    only a guard against an unbounded prompt after years of daily episodes.
    Deduplicated case-insensitively so a repeat that slipped through doesn't
    consume two slots.
    """

    if not report_type_id:
        return []
    rows = session.exec(
        select(ReportedItem)
        .where(ReportedItem.report_type == report_type_id)
        .order_by(ReportedItem.created_at.desc(), ReportedItem.id.desc())
    ).all()
    seen: set[str] = set()
    items: list[str] = []
    for row in rows:
        key = row.item.strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        items.append(row.item.strip())
        if len(items) >= limit:
            break
    return items


def _past_market_comments(
    session: Session,
    *,
    limit: int = MARKET_COMMENTS_PROMPT_LIMIT,
) -> list[str]:
    """Market asides from past episodes, most-recent first, deduplicated."""

    rows = session.exec(
        select(Episode.market_comment)
        .where(Episode.market_comment != "")
        .order_by(Episode.created_at.desc(), Episode.id.desc())
        .limit(limit)
    ).all()
    seen: set[str] = set()
    comments: list[str] = []
    for comment in rows:
        text = (comment or "").strip()
        key = text.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        comments.append(text)
    return comments


def _covered_item_count(session: Session, report_type_id: str) -> int:
    """How many items this report type has covered in total, including duplicates."""

    from sqlalchemy import func

    if not report_type_id:
        return 0
    return session.exec(
        select(func.count())
        .select_from(ReportedItem)
        .where(ReportedItem.report_type == report_type_id)
    ).one()


def _pick_variety_axis(report_type_id: str, covered_count: int) -> str:
    """Choose today's rotating angle for a report type that defines any."""

    report_type = get_report_type(report_type_id)
    if report_type is None or not report_type.variety_axes:
        return ""
    axes = report_type.variety_axes
    # Step through the axes rather than sampling, so a short run of episodes
    # can't draw the same angle twice.
    return axes[covered_count % len(axes)]


def _summarize_long_articles(
    articles: list[news.Article],
    settings: Settings,
    credentials: Credentials,
) -> None:
    limit = settings.max_article_length
    audit = active_log()
    for article in articles:
        body = article.body
        if body and len(body) > limit:
            try:
                timer = LogTimer.start()
                article.body = llm.summarize_article(
                    body,
                    limit,
                    credentials=credentials,
                    llm_provider=settings.llm_provider,
                    llm_model=settings.llm_model,
                )
                if audit is not None:
                    audit.record(
                        "llm",
                        "Summarize long article",
                        summary=f"{article.title[:80]}",
                        request={
                            "title": article.title,
                            "original_chars": len(body),
                            "target_chars": limit,
                            "original_text": body,
                        },
                        response={
                            "summary_chars": len(article.body),
                            "summary_text": article.body,
                        },
                        duration_ms=timer.elapsed_ms(),
                    )
            except llm.LLMError as error:
                if audit is not None:
                    audit.record(
                        "llm",
                        "Summarize long article",
                        status="error",
                        summary=f"{article.title[:80]} — truncated instead",
                        response={"error": str(error)},
                    )
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
