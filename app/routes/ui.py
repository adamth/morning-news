"""Dashboard, episode pages, and settings management."""

from __future__ import annotations

import logging
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlmodel import Session, func, select

from ..auth import create_user, web_user
from ..audio import probe_duration
from ..config import config
from ..credentials import apply_secret_updates, load_credentials
from ..db import (
    CalendarFeed,
    Episode,
    EpisodeArticle,
    EpisodeLogEntry,
    EpisodeStatus,
    Message,
    MessageStatus,
    Preference,
    ReportedItem,
    Source,
    User,
    WatchlistItem,
    WeeklyReport,
    get_session,
    get_settings,
    utcnow,
)
from ..episodes import EpisodeDeleteError, delete_episode
from ..episode_log import category_label
from ..health import get_health_report
from ..places import parse_places, serialize_places
from ..report_types import REPORT_TYPES, WEEKDAY_LABELS
from ..llm_models import list_chat_models
from ..llm_providers import (
    DEFAULT_LLM_MODELS,
    LlmProviderId,
    PROVIDER_LABELS,
    available_providers,
    normalize_model,
    resolve_provider,
)
from ..pipeline import generate_episode_background
from ..scheduler import reschedule
from ..sources import news, weather
from ..templating import templates
from ..tts import (
    DEFAULT_VOICE_IDS,
    DEFAULT_VOICE_MODELS,
    SPEECHIFY_EMOTION_OPTIONS,
    TTS_PROVIDER_LABELS,
    VOICE_MODEL_OPTIONS,
    TtsProviderId,
    available_tts_providers,
    get_provider,
    list_voice_options,
    normalize_speechify_emotion,
    normalize_voice_model,
    resolve_tts_provider,
)
from ..urls import resolve_base_url

logger = logging.getLogger(__name__)
router = APIRouter()

SETTINGS_SECTIONS: tuple[tuple[str, str], ...] = (
    ("schedule", "Schedule"),
    ("content", "In the show"),
    ("voice", "Voice"),
    ("music", "Music"),
    ("feed", "Podcast feed"),
    ("household", "Household"),
    ("connections", "Connections"),
    ("health", "Health"),
)


def _split_comma_list(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _settings_redirect(anchor: str, *, msg: str = "", err: str = "") -> RedirectResponse:
    query = f"?msg={quote_plus(msg)}" if msg else f"?err={quote_plus(err)}" if err else ""
    return RedirectResponse(f"/settings{query}#{anchor}", status_code=303)


def _episode_numbers(session: Session, episodes: list[Episode]) -> dict[int, int]:
    """Map episode id to its position in the run, counting from the first ever episode."""

    total = session.exec(select(func.count()).select_from(Episode)).one()
    return {
        episode.id: total - offset
        for offset, episode in enumerate(episodes)
        if episode.id is not None
    }


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    messages = session.exec(
        select(Message)
        .where(Message.author_user_id == user.id)
        .order_by(Message.created_at.desc())
    ).all()
    episodes = session.exec(select(Episode).order_by(Episode.created_at.desc()).limit(30)).all()
    latest_episode = episodes[0] if episodes else None
    latest_episode_article_count = 0
    latest_episode_message_count = 0
    if latest_episode and latest_episode.id is not None:
        latest_episode_article_count = len(
            session.exec(
                select(EpisodeArticle).where(EpisodeArticle.episode_id == latest_episode.id)
            ).all()
        )
        latest_episode_message_count = len(
            session.exec(
                select(Message).where(Message.episode_id == latest_episode.id)
            ).all()
        )
    base_url = resolve_base_url(request)
    pending_message_count = sum(
        1 for message in messages if message.status == MessageStatus.pending
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "active": "episodes",
            "messages": messages,
            "episodes": episodes,
            "episode_numbers": _episode_numbers(session, episodes),
            "feed_url": f"{base_url}/feed.xml?token={settings.feed_token}",
            "latest_episode_url": f"{base_url}/media/latest.mp3",
            "settings": settings,
            "household_timezone": settings.timezone,
            "pending_message_count": pending_message_count,
            "setup_incomplete": settings.latitude is None or not settings.locality.strip(),
            "location_label": settings.locality.strip() or settings.address.strip() or None,
            "latest_episode_article_count": latest_episode_article_count,
            "latest_episode_message_count": latest_episode_message_count,
        },
    )


@router.get("/api/episodes/latest")
def latest_episode_status(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    episode = session.exec(
        select(Episode).order_by(Episode.created_at.desc()).limit(1)
    ).first()
    if episode is None:
        return JSONResponse({"episode": None})
    return JSONResponse(
        {
            "episode": {
                "id": episode.id,
                "status": episode.status.value,
                "title": episode.title,
                "duration_seconds": episode.duration_seconds,
                "error": episode.error,
            }
        }
    )


@router.post("/episodes/{episode_id}/delete")
def delete_episode_route(
    episode_id: int,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    try:
        delete_episode(session, episode_id)
    except EpisodeDeleteError as error:
        return RedirectResponse(
            f"/episodes/{episode_id}?err={quote_plus(str(error))}", status_code=303
        )
    return RedirectResponse("/?msg=Episode+deleted.", status_code=303)


@router.get("/episodes/{episode_id}", response_class=HTMLResponse)
def episode_page(
    episode_id: int,
    request: Request,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    episode = session.get(Episode, episode_id)
    if episode is None:
        return RedirectResponse("/?err=Episode+not+found", status_code=303)
    articles = session.exec(
        select(EpisodeArticle).where(EpisodeArticle.episode_id == episode_id)
    ).all()
    reported_items = session.exec(
        select(ReportedItem).where(ReportedItem.episode_id == episode_id)
    ).all()
    log_entries = session.exec(
        select(EpisodeLogEntry)
        .where(EpisodeLogEntry.episode_id == episode_id)
        .order_by(EpisodeLogEntry.sequence)
    ).all()
    episode_number = session.exec(
        select(func.count())
        .select_from(Episode)
        .where(Episode.created_at <= episode.created_at)
    ).one()
    return templates.TemplateResponse(
        request,
        "episode.html",
        {
            "user": user,
            "active": "episodes",
            "episode": episode,
            "episode_number": episode_number,
            "household_timezone": get_settings(session).timezone,
            "articles": articles,
            "reported_items": reported_items,
            "log_groups": _group_log_entries(log_entries),
            "media_url": f"{resolve_base_url(request)}/media/{episode.id}.mp3",
        },
    )


def _group_log_entries(entries: list[EpisodeLogEntry]) -> list[dict]:
    """Group audit log entries by category, preserving first-seen order."""

    groups: list[dict] = []
    index_by_category: dict[str, int] = {}

    for entry in entries:
        if entry.category not in index_by_category:
            index_by_category[entry.category] = len(groups)
            groups.append(
                {
                    "category": entry.category,
                    "label": category_label(entry.category),
                    "entries": [],
                }
            )
        groups[index_by_category[entry.category]]["entries"].append(entry)

    return groups


@router.post("/generate")
def generate_now(
    background_tasks: BackgroundTasks,
    user: User = Depends(web_user),
):
    background_tasks.add_task(generate_episode_background)
    return RedirectResponse(
        "/?generating=1&msg=Generating+episode+in+the+background",
        status_code=303,
    )


def _setup_checklist(session: Session, settings) -> dict | None:
    """First-run checklist state; None once every step is complete."""
    credentials = load_credentials(settings)
    keys_done = bool(available_tts_providers(credentials)) and bool(
        available_providers(credentials)
    )
    town_done = settings.latitude is not None
    listen_done = (
        session.exec(select(Episode).where(Episode.status == EpisodeStatus.ready)).first()
        is not None
    )
    if keys_done and town_done and listen_done:
        return None
    return {
        "keys_done": keys_done,
        "town_done": town_done,
        "listen_done": listen_done,
        "ready_to_build": keys_done and town_done,
        "build_time": f"{settings.schedule_hour:02d}:{settings.schedule_minute:02d}",
    }


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    refresh: bool = False,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    credentials = load_credentials(settings)
    base_url = resolve_base_url(request)
    tts_provider = resolve_tts_provider(
        credentials=credentials, settings_provider=settings.tts_provider
    )
    configured_tts = available_tts_providers(credentials)
    llm_provider = resolve_provider(
        credentials=credentials,
        settings_provider=settings.llm_provider,
        settings_model=settings.llm_model,
    )
    configured_providers = available_providers(credentials)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "active": "settings",
            "s": settings,
            "household_timezone": settings.timezone,
            "setup": _setup_checklist(session, settings),
            "sections": SETTINGS_SECTIONS,
            "credentials": credentials,
            "feed_url": f"{base_url}/feed.xml?token={settings.feed_token}",
            "latest_episode_url": f"{base_url}/media/latest.mp3",
            "users": session.exec(select(User).order_by(User.created_at)).all(),
            "calendars": session.exec(
                select(CalendarFeed).order_by(CalendarFeed.created_at)
            ).all(),
            "preferences": session.exec(select(Preference).order_by(Preference.created_at)).all(),
            "watchlist": session.exec(
                select(WatchlistItem).order_by(WatchlistItem.created_at)
            ).all(),
            "sources": session.exec(select(Source).order_by(Source.created_at)).all(),
            "weekly_reports": _weekly_report_map(session),
            "weekly_report_days": WEEKDAY_LABELS,
            "report_type_options": REPORT_TYPES,
            "voices": _safe_list_voices(settings, credentials),
            "tts_provider": tts_provider.value,
            "tts_provider_options": [
                {
                    "id": provider.value,
                    "label": TTS_PROVIDER_LABELS[provider],
                    "configured": provider in configured_tts,
                }
                for provider in TtsProviderId
            ],
            "voice_model_options": VOICE_MODEL_OPTIONS[tts_provider],
            "voice_model": normalize_voice_model(tts_provider, settings.voice_model),
            "speechify_emotion_options": SPEECHIFY_EMOTION_OPTIONS,
            "speechify_emotion": normalize_speechify_emotion(settings.speechify_emotion),
            "intro_exists": config.intro_path.exists(),
            "intro_duration": (
                probe_duration(config.intro_path) if config.intro_path.exists() else None
            ),
            "outro_exists": config.outro_path.exists(),
            "outro_duration": (
                probe_duration(config.outro_path) if config.outro_path.exists() else None
            ),
            "llm_models": list_chat_models(llm_provider, credentials=credentials),
            "llm_provider": llm_provider.value,
            "llm_provider_options": [
                {
                    "id": provider.value,
                    "label": PROVIDER_LABELS[provider],
                    "configured": provider in configured_providers,
                    "default_model": DEFAULT_LLM_MODELS[provider],
                }
                for provider in LlmProviderId
            ],
            "report": get_health_report(force_refresh=refresh),
        },
    )


@router.get("/settings/household")
def household_redirect():
    return RedirectResponse("/settings#household", status_code=301)


@router.get("/settings/plumbing")
def plumbing_redirect():
    return RedirectResponse("/settings#connections", status_code=301)


@router.get("/settings/connections")
def connections_redirect():
    return RedirectResponse("/settings#connections", status_code=301)


@router.get("/settings/status")
def status_redirect():
    return RedirectResponse("/settings#health", status_code=301)


@router.get("/settings/advanced")
def advanced_redirect():
    return RedirectResponse("/settings", status_code=301)


@router.post("/settings/connections")
def save_connections_settings(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    elevenlabs_api_key: str = Form(""),
    speechify_api_key: str = Form(""),
    openrouter_api_key: str = Form(""),
    openai_api_key: str = Form(""),
    anthropic_api_key: str = Form(""),
    llm_api_key: str = Form(""),
    llm_base_url: str = Form(""),
    zyte_api_key: str = Form(""),
    finnhub_api_key: str = Form(""),
    weatherapi_api_key: str = Form(""),
    clear_elevenlabs: str | None = Form(None),
    clear_speechify: str | None = Form(None),
    clear_openrouter: str | None = Form(None),
    clear_openai: str | None = Form(None),
    clear_anthropic: str | None = Form(None),
    clear_llm: str | None = Form(None),
    clear_zyte: str | None = Form(None),
    clear_finnhub: str | None = Form(None),
    clear_weatherapi: str | None = Form(None),
):
    settings = get_settings(session)
    apply_secret_updates(
        settings,
        elevenlabs_api_key=elevenlabs_api_key,
        speechify_api_key=speechify_api_key,
        openrouter_api_key=openrouter_api_key,
        openai_api_key=openai_api_key,
        anthropic_api_key=anthropic_api_key,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        zyte_api_key=zyte_api_key,
        finnhub_api_key=finnhub_api_key,
        weatherapi_api_key=weatherapi_api_key,
        clear_elevenlabs=clear_elevenlabs is not None,
        clear_speechify=clear_speechify is not None,
        clear_openrouter=clear_openrouter is not None,
        clear_openai=clear_openai is not None,
        clear_anthropic=clear_anthropic is not None,
        clear_llm=clear_llm is not None,
        clear_zyte=clear_zyte is not None,
        clear_finnhub=clear_finnhub is not None,
        clear_weatherapi=clear_weatherapi is not None,
    )
    settings.updated_at = utcnow()
    session.add(settings)
    session.commit()
    return _settings_redirect(
        "connections", msg="Keys saved. The health checks below confirm everything connects."
    )


@router.get("/api/health")
def health_status_api(
    refresh: bool = False,
    user: User = Depends(web_user),
):
    return JSONResponse(get_health_report(force_refresh=refresh).to_dict())


@router.get("/api/locations/search")
def location_search(
    q: str = Query(""),
    user: User = Depends(web_user),
):
    payload = []
    for result in weather.search_locations(q):
        news_hl, news_gl, news_ceid = weather.news_edition_for_country(result.country_code)
        payload.append(
            {
                "id": result.open_meteo_id,
                "label": result.display_label,
                "locality": result.locality,
                "latitude": result.latitude,
                "longitude": result.longitude,
                "timezone": result.timezone,
                "country_code": result.country_code,
                "admin1": result.admin1,
                "country": result.country,
                "news_hl": news_hl,
                "news_gl": news_gl,
                "news_ceid": news_ceid,
            }
        )
    return JSONResponse(payload)


@router.get("/api/llm/models")
def llm_model_search(
    provider: str = Query("openrouter"),
    q: str = Query(""),
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    credentials = load_credentials(settings)
    try:
        provider_id = LlmProviderId(provider.strip().lower())
    except ValueError:
        provider_id = LlmProviderId.openrouter

    query = q.strip().lower()
    models = list_chat_models(provider_id, credentials=credentials)
    if query:
        models = [
            model
            for model in models
            if query in model.id.lower() or query in model.name.lower()
        ]
    return JSONResponse([{"id": model.id, "label": model.label} for model in models[:25]])


@router.get("/api/tts/voices")
def tts_voice_options_api(
    provider: str = Query(""),
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    credentials = load_credentials(settings)
    provider_id = resolve_tts_provider(
        credentials=credentials,
        settings_provider=provider.strip() or settings.tts_provider,
    )
    configured = provider_id in available_tts_providers(credentials)
    voices: list = []
    if configured:
        try:
            voices = list_voice_options(
                get_provider(credentials=credentials, settings_provider=provider_id.value),
                news_hl=settings.news_hl,
            )
        except Exception as error:
            logger.info("Voice listing unavailable: %s", error)

    return JSONResponse(
        {
            "provider": provider_id.value,
            "configured": configured,
            "voices": [
                {
                    "voice_id": voice.voice_id,
                    "name": voice.name,
                    "accent": voice.accent,
                    "preview_url": voice.preview_url,
                }
                for voice in voices
            ],
            "voice_models": [
                {"id": model_id, "label": label}
                for model_id, label in VOICE_MODEL_OPTIONS[provider_id]
            ],
            "default_voice_id": DEFAULT_VOICE_IDS[provider_id],
            "default_voice_model": DEFAULT_VOICE_MODELS[provider_id],
            "speechify_emotions": [
                {"id": emotion_id, "label": label}
                for emotion_id, label in SPEECHIFY_EMOTION_OPTIONS
            ],
            "show_speechify_tone": provider_id is TtsProviderId.speechify,
        }
    )


@router.get("/api/openrouter/models")
def openrouter_model_search(
    q: str = Query(""),
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    return llm_model_search(
        provider=LlmProviderId.openrouter.value, q=q, user=user, session=session
    )


@router.post("/settings")
def save_settings(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    schedule_time: str = Form("07:00"),
    timezone: str = Form("UTC"),
    address: str = Form(""),
    location_confirmed: str = Form(""),
    latitude: str = Form(""),
    longitude: str = Form(""),
    locality: str = Form(""),
    country_code: str = Form(""),
    admin1: str = Form(""),
    country: str = Form(""),
    news_hl: str = Form("en-US"),
    news_gl: str = Form("US"),
    news_ceid: str = Form("US:en"),
    home_places: str = Form(""),
    target_minutes_min: float = Form(1.5),
    target_minutes_max: float = Form(3.0),
):
    settings = get_settings(session)
    settings.home_places = serialize_places(parse_places(home_places))

    settings.schedule_hour, settings.schedule_minute = _parse_time(schedule_time)

    timezone_name = timezone.strip() or "UTC"
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return _settings_redirect(
            "schedule",
            err=(
                "That time zone isn't recognised. It fills in automatically "
                "when you pick your town from the list."
            ),
        )

    if target_minutes_max < target_minutes_min:
        return _settings_redirect(
            "schedule",
            err="The longest length can't be shorter than the shortest. Swap the two numbers.",
        )

    address = address.strip()
    if address:
        if location_confirmed != "1" or not latitude or not longitude or not locality:
            return _settings_redirect(
                "schedule", err="Choose your town from the list before saving."
            )
        try:
            settings.latitude = float(latitude)
            settings.longitude = float(longitude)
        except ValueError:
            return _settings_redirect(
                "schedule", err="That town didn't save. Select one from the list and try again."
            )
        settings.address = address
        settings.locality = locality.strip()
        settings.admin1 = admin1.strip()
        settings.country = country.strip()
        settings.timezone = timezone_name
        if country_code.strip():
            news_hl, news_gl, news_ceid = weather.news_edition_for_country(country_code.strip())
    else:
        settings.address = ""
        settings.locality = ""
        settings.admin1 = ""
        settings.country = ""
        settings.latitude = None
        settings.longitude = None

    settings.news_hl = news_hl.strip() or "en-US"
    settings.news_gl = news_gl.strip() or "US"
    settings.news_ceid = news_ceid.strip() or "US:en"
    settings.target_minutes_min = max(0.5, target_minutes_min)
    settings.target_minutes_max = target_minutes_max
    settings.updated_at = utcnow()

    session.add(settings)
    session.commit()
    reschedule()
    return _settings_redirect("schedule", msg="Schedule saved. The next episode will use it.")


@router.post("/settings/content")
def save_content_settings(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    weather_enabled: str | None = Form(None),
    stocks_enabled: str | None = Form(None),
):
    settings = get_settings(session)
    settings.weather_enabled = weather_enabled is not None
    settings.stocks_enabled = stocks_enabled is not None
    settings.updated_at = utcnow()
    session.add(settings)
    session.commit()
    return _settings_redirect("content", msg="Saved.")


@router.post("/settings/interests")
def save_interest_topics(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    interest_topics: str = Form(""),
):
    settings = get_settings(session)
    settings.interest_topics = serialize_places(parse_places(interest_topics))
    settings.updated_at = utcnow()
    session.add(settings)
    session.commit()
    return _settings_redirect("interests", msg="Slow-day interests saved.")


@router.post("/calendars")
def add_calendar(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    url: str = Form(...),
    label: str = Form(""),
):
    calendar_url = url.strip()
    if not calendar_url:
        return _settings_redirect("calendars", err="Paste a calendar link to add it.")
    session.add(CalendarFeed(url=calendar_url, label=label.strip()))
    session.commit()
    return _settings_redirect("calendars", msg="Calendar added.")


@router.post("/calendars/{feed_id}/toggle")
def toggle_calendar(
    feed_id: int,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    feed = session.get(CalendarFeed, feed_id)
    message = "Calendar not found."
    if feed is not None:
        feed.enabled = not feed.enabled
        session.add(feed)
        session.commit()
        message = "Calendar turned on." if feed.enabled else "Calendar turned off."
    return _settings_redirect("calendars", msg=message)


@router.post("/calendars/{feed_id}/delete")
def delete_calendar(
    feed_id: int,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    feed = session.get(CalendarFeed, feed_id)
    if feed is not None:
        session.delete(feed)
        session.commit()
    return _settings_redirect("calendars", msg="Calendar removed.")


@router.post("/watchlist")
def add_watchlist_item(
    symbol: str = Form(...),
    label: str = Form(""),
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    from ..sources import stocks

    symbols = _split_comma_list(symbol)
    if not symbols:
        return _settings_redirect("stocks", err="Enter at least one ticker symbol.")

    existing_symbols = {item.symbol for item in session.exec(select(WatchlistItem)).all()}
    label_text = label.strip()
    use_label = label_text if len(symbols) == 1 else ""

    added: list[str] = []
    invalid: list[str] = []
    duplicates: list[str] = []

    for raw in symbols:
        normalized = stocks.normalize_symbol(raw)
        if not normalized:
            invalid.append(raw)
            continue
        if normalized in existing_symbols:
            duplicates.append(normalized)
            continue
        session.add(WatchlistItem(symbol=normalized, label=use_label))
        existing_symbols.add(normalized)
        added.append(normalized)

    if added:
        session.commit()

    if not added:
        if invalid and not duplicates:
            return _settings_redirect(
                "stocks", err="Enter valid ticker symbols (e.g. AAPL or ^GSPC)."
            )
        if duplicates and not invalid:
            return _settings_redirect(
                "stocks",
                err=(
                    "That ticker is already on your watchlist."
                    if len(symbols) == 1
                    else "Those tickers are already on your watchlist."
                ),
            )
        return _settings_redirect(
            "stocks", err="No new stocks added. Check the ticker symbols and try again."
        )

    message = (
        "Stock added to the watchlist."
        if len(added) == 1
        else f"{len(added)} stocks added to the watchlist."
    )
    extras: list[str] = []
    if invalid:
        extras.append(f"skipped invalid: {', '.join(invalid)}")
    if duplicates:
        extras.append(f"already listed: {', '.join(duplicates)}")
    if extras:
        message += " (" + "; ".join(extras) + ")"
    return _settings_redirect("stocks", msg=message)


@router.post("/watchlist/{item_id}/delete")
def delete_watchlist_item(
    item_id: int,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    item = session.get(WatchlistItem, item_id)
    if item is not None:
        session.delete(item)
        session.commit()
    return _settings_redirect("stocks", msg="Stock removed from the watchlist.")


@router.post("/settings/weekly-reports")
def save_weekly_reports(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    report_type: list[str] = Form(default=[]),
    user_input: list[str] = Form(default=[]),
):
    """Persist per-weekday special-report configuration.

    The form submits two parallel lists indexed by day position (0–6):
    `report_type` and `user_input`. Empty `report_type` means "regular daily
    news" — we still keep the row (and its `user_input`) so the user's notes
    survive if they toggle a day off and back on.
    """

    if len(report_type) != 7 or len(user_input) != 7:
        return _settings_redirect(
            "weekly", err="Weekly report settings were malformed. Please try again."
        )

    existing = {row.day_of_week: row for row in session.exec(select(WeeklyReport)).all()}
    changed = False
    for day in range(7):
        new_type = (report_type[day] or "").strip()
        new_input = (user_input[day] or "").strip()
        if new_type and new_type not in {rt.id for rt in REPORT_TYPES}:
            new_type = ""
        row = existing.get(day)
        if row is None:
            if new_type or new_input:
                session.add(
                    WeeklyReport(
                        day_of_week=day,
                        report_type=new_type,
                        user_input=new_input,
                        updated_at=utcnow(),
                    )
                )
                changed = True
            continue
        if row.report_type != new_type or row.user_input != new_input:
            row.report_type = new_type
            row.user_input = new_input
            row.updated_at = utcnow()
            session.add(row)
            changed = True

    if changed:
        session.commit()
        return _settings_redirect("weekly", msg="Weekly focus saved.")
    return _settings_redirect("weekly", msg="No changes to save.")


@router.post("/settings/voice")
def save_voice_settings(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    tts_provider: str = Form(""),
    voice_id: str = Form(""),
    voice_model: str = Form("eleven_v3"),
    voice_randomize: str | None = Form(None),
    speechify_emotion: str = Form(""),
):
    settings = get_settings(session)
    credentials = load_credentials(settings)
    previous_provider = resolve_tts_provider(
        credentials=credentials, settings_provider=settings.tts_provider
    )
    new_provider = resolve_tts_provider(
        credentials=credentials, settings_provider=tts_provider or settings.tts_provider
    )
    settings.tts_provider = new_provider.value

    message = "Narrator voice saved."
    if new_provider != previous_provider:
        # The submitted voice/model belong to the old service — start from the
        # new service's defaults and let the reloaded page offer its voices.
        settings.voice_id = DEFAULT_VOICE_IDS[new_provider]
        settings.voice_model = DEFAULT_VOICE_MODELS[new_provider]
        message = "Narration service changed. Pick a voice from the updated list."
    else:
        settings.voice_id = voice_id.strip() or settings.voice_id
        settings.voice_model = normalize_voice_model(
            new_provider, voice_model.strip() or settings.voice_model
        )
    settings.voice_randomize = voice_randomize is not None
    if new_provider is TtsProviderId.speechify:
        settings.speechify_emotion = normalize_speechify_emotion(speechify_emotion)
    settings.updated_at = utcnow()
    session.add(settings)
    session.commit()
    return _settings_redirect("voice", msg=message)


@router.post("/settings/feed")
def save_feed_settings(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    podcast_title: str = Form("Morning News"),
    podcast_author: str = Form("Morning News"),
    podcast_description: str = Form(""),
):
    settings = get_settings(session)
    settings.podcast_title = podcast_title.strip() or "Morning News"
    settings.podcast_author = podcast_author.strip() or "Morning News"
    settings.podcast_description = podcast_description.strip()
    settings.updated_at = utcnow()
    session.add(settings)
    session.commit()
    return _settings_redirect("feed", msg="Podcast details saved.")


@router.post("/settings/writer")
def save_writer_settings(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    llm_provider: str = Form(""),
    llm_model: str = Form("openai/gpt-4o-mini"),
):
    settings = get_settings(session)
    fallback = resolve_provider(
        credentials=load_credentials(settings),
        settings_provider=settings.llm_provider,
        settings_model=settings.llm_model,
    )
    try:
        provider_id = LlmProviderId(
            (llm_provider or settings.llm_provider or fallback).strip().lower()
        )
    except ValueError:
        provider_id = fallback
    settings.llm_provider = provider_id.value
    settings.llm_model = normalize_model(provider_id, llm_model.strip() or settings.llm_model)
    settings.updated_at = utcnow()
    session.add(settings)
    session.commit()
    return _settings_redirect("connections", msg="Script writer saved.")


@router.post("/settings/music")
async def save_music(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    intro: UploadFile | None = File(None),
    outro: UploadFile | None = File(None),
    intro_play_seconds: float = Form(6.0),
    outro_play_seconds: float = Form(2.0),
    remove_intro: str | None = Form(None),
    remove_outro: str | None = Form(None),
):
    settings = get_settings(session)
    settings.intro_play_seconds = max(0.0, intro_play_seconds)
    settings.outro_play_seconds = max(0.0, outro_play_seconds)
    settings.updated_at = utcnow()

    for upload, remove, path, name in (
        (intro, remove_intro, config.intro_path, "Intro"),
        (outro, remove_outro, config.outro_path, "Outro"),
    ):
        if remove is not None:
            path.unlink(missing_ok=True)
            continue
        if upload is None or not upload.filename:
            continue
        data = await upload.read()
        if not data:
            return _settings_redirect(
                "music", err=f"That {name.lower()} file was empty. Choose a different MP3."
            )
        path.write_bytes(data)

    session.add(settings)
    session.commit()
    return _settings_redirect("music", msg="Music saved.")


@router.post("/sources")
def add_source(
    url: str = Form(...),
    name: str = Form(""),
    priority: str | None = Form(None),
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    url = url.strip()
    message = "News feed added."
    if url:
        feed_url, is_feed = news.resolve_feed_url(url)
        if feed_url != url:
            message = f"News feed added — using the feed found at {feed_url}."
        elif not is_feed:
            message = (
                "Feed added, but that link doesn't look like an RSS feed "
                "and no feed was found on the page — it may return no stories."
            )
        session.add(Source(url=feed_url, name=name.strip(), priority=bool(priority)))
        session.commit()
    return _settings_redirect("feeds", msg=message)


@router.post("/sources/{source_id}/priority")
def toggle_source_priority(
    source_id: int,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    source = session.get(Source, source_id)
    message = "News feed not found."
    if source is not None:
        source.priority = not source.priority
        session.add(source)
        session.commit()
        message = (
            "Feed stories will always be included."
            if source.priority
            else "Feed returned to normal priority."
        )
    return _settings_redirect("feeds", msg=message)


@router.post("/sources/{source_id}/delete")
def delete_source(
    source_id: int,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    source = session.get(Source, source_id)
    if source is not None:
        session.delete(source)
        session.commit()
    return _settings_redirect("feeds", msg="News feed deleted.")


@router.post("/preferences")
def add_preference(
    topic: str = Form(...),
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    topics = _split_comma_list(topic)
    if not topics:
        return _settings_redirect("skip", err="Enter at least one topic.")

    existing_topics = {
        preference.topic.casefold() for preference in session.exec(select(Preference)).all()
    }

    added: list[str] = []
    for candidate in topics:
        key = candidate.casefold()
        if key in existing_topics:
            continue
        session.add(Preference(topic=candidate))
        existing_topics.add(key)
        added.append(candidate)

    if added:
        session.commit()

    if not added:
        return _settings_redirect(
            "skip",
            err=(
                "That topic is already on the skip list."
                if len(topics) == 1
                else "Those topics are already on the skip list."
            ),
        )

    message = (
        "Topic added to the skip list."
        if len(added) == 1
        else f"{len(added)} topics added to the skip list."
    )
    skipped = len(topics) - len(added)
    if skipped:
        message += f" ({skipped} already listed)"
    return _settings_redirect("skip", msg=message)


@router.post("/preferences/{preference_id}/delete")
def delete_preference(
    preference_id: int,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    preference = session.get(Preference, preference_id)
    if preference is not None:
        session.delete(preference)
        session.commit()
    return _settings_redirect("skip", msg="Topic removed from the skip list.")


@router.post("/users")
def add_user(
    username: str = Form(...),
    password: str = Form(...),
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    username = username.strip()
    if not username or not password:
        return _settings_redirect(
            "household", err="Enter a username and password for the new person."
        )
    if session.exec(select(User).where(User.username == username)).first() is not None:
        return _settings_redirect(
            "household", err="That username is already in use. Try a different one."
        )
    create_user(session, username, password)
    return _settings_redirect("household", msg="Household member added.")


def _weekly_report_map(session: Session) -> dict[int, WeeklyReport]:
    """Return a {day_of_week: WeeklyReport} map covering all 7 days."""

    by_day = {row.day_of_week: row for row in session.exec(select(WeeklyReport)).all()}
    for day in range(7):
        if day not in by_day:
            by_day[day] = WeeklyReport(day_of_week=day, report_type="", user_input="")
    return by_day


def _safe_list_voices(settings, credentials):
    try:
        return list_voice_options(
            get_provider(credentials=credentials, settings_provider=settings.tts_provider),
            news_hl=settings.news_hl,
        )
    except Exception as error:
        logger.info("Voice listing unavailable: %s", error)
        return []


def _parse_time(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        return max(0, min(23, int(hour_text))), max(0, min(59, int(minute_text)))
    except (ValueError, AttributeError):
        return 7, 0
