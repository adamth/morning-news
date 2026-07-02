"""Dashboard, episode pages, and settings management."""

from __future__ import annotations

import logging
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlmodel import Session, select

from ..auth import create_user, web_user
from ..audio import probe_duration
from ..config import config
from ..credentials import apply_secret_updates, load_credentials
from ..db import (
    Episode,
    EpisodeArticle,
    EpisodeLogEntry,
    EpisodeStatus,
    Message,
    MessageStatus,
    Preference,
    Source,
    User,
    WatchlistItem,
    get_session,
    get_settings,
    utcnow,
)
from ..episode_log import category_label
from ..health import get_health_report
from ..news_categories import NEWS_CATEGORIES, parse_selected, serialize_selected
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
from ..sources.weather_providers import (
    WEATHER_PROVIDER_LABELS,
    WeatherProviderId,
    resolve_weather_provider,
    weatherapi_configured,
)
from ..templating import templates
from ..tts import (
    DEFAULT_VOICE_IDS,
    DEFAULT_VOICE_MODELS,
    SPEECHIFY_EMOTION_OPTIONS,
    TTS_PROVIDER_LABELS,
    VOICE_LANGUAGE_OPTIONS,
    VOICE_MODEL_OPTIONS,
    TtsProviderId,
    available_tts_providers,
    get_provider,
    list_accent_options,
    list_voice_options,
    normalize_speechify_emotion,
    normalize_voice_model,
    resolve_tts_provider,
)
from ..urls import resolve_base_url

logger = logging.getLogger(__name__)
router = APIRouter()


def _split_comma_list(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


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
    latest_episode_media_url = None
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
        if (
            latest_episode.status == EpisodeStatus.ready
            and latest_episode.audio_path
        ):
            latest_episode_media_url = (
                f"{resolve_base_url(request)}/media/{latest_episode.id}.mp3"
                f"?token={settings.feed_token}"
            )
    base_url = resolve_base_url(request)
    feed_url = f"{base_url}/feed.xml?token={settings.feed_token}"
    pending_message_count = sum(
        1 for message in messages if message.status == MessageStatus.pending
    )
    setup_incomplete = settings.latitude is None or not settings.locality.strip()
    location_label = settings.locality.strip() or settings.address.strip() or None
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "active": "dashboard",
            "messages": messages,
            "episodes": episodes,
            "feed_url": feed_url,
            "settings": settings,
            "pending_message_count": pending_message_count,
            "setup_incomplete": setup_incomplete,
            "location_label": location_label,
            "latest_episode_article_count": latest_episode_article_count,
            "latest_episode_message_count": latest_episode_message_count,
            "latest_episode_media_url": latest_episode_media_url,
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
    log_entries = session.exec(
        select(EpisodeLogEntry)
        .where(EpisodeLogEntry.episode_id == episode_id)
        .order_by(EpisodeLogEntry.sequence)
    ).all()
    log_groups = _group_log_entries(log_entries)
    settings = get_settings(session)
    media_url = f"{resolve_base_url(request)}/media/{episode.id}.mp3?token={settings.feed_token}"
    return templates.TemplateResponse(
        request,
        "episode.html",
        {
            "user": user,
            "active": "dashboard",
            "episode": episode,
            "articles": articles,
            "log_groups": log_groups,
            "media_url": media_url,
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
    keys_done = bool(available_tts_providers(credentials)) and bool(available_providers(credentials))
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
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    credentials = load_credentials(settings)
    preferences = session.exec(select(Preference).order_by(Preference.created_at)).all()
    watchlist = session.exec(select(WatchlistItem).order_by(WatchlistItem.created_at)).all()
    intro_duration = (
        probe_duration(config.intro_path) if config.intro_path.exists() else None
    )
    outro_duration = (
        probe_duration(config.outro_path) if config.outro_path.exists() else None
    )
    tts_provider = resolve_tts_provider(
        credentials=credentials, settings_provider=settings.tts_provider
    )
    configured_tts = available_tts_providers(credentials)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "active": "settings",
            "settings_tab": "show",
            "s": settings,
            "setup": _setup_checklist(session, settings),
            "preferences": preferences,
            "watchlist": watchlist,
            "news_categories": NEWS_CATEGORIES,
            "selected_categories": set(parse_selected(settings.preferred_categories)),
            "voices": _safe_list_voices(settings, credentials),
            "voice_accents": _safe_list_accents(settings, credentials),
            "voice_languages": VOICE_LANGUAGE_OPTIONS,
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
            "intro_duration": intro_duration,
            "outro_exists": config.outro_path.exists(),
            "outro_duration": outro_duration,
            "weather_provider": resolve_weather_provider(settings.weather_provider).value,
            "weather_provider_options": [
                {
                    "id": provider.value,
                    "label": WEATHER_PROVIDER_LABELS[provider],
                    "configured": (
                        True
                        if provider is not WeatherProviderId.weatherapi
                        else weatherapi_configured(credentials.weatherapi_api_key)
                    ),
                }
                for provider in WeatherProviderId
            ],
        },
    )


@router.get("/settings/household", response_class=HTMLResponse)
def household_settings_page(
    request: Request,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    users = session.exec(select(User).order_by(User.created_at)).all()
    return templates.TemplateResponse(
        request,
        "settings_household.html",
        {
            "user": user,
            "active": "settings",
            "settings_tab": "household",
            "s": settings,
            "setup": _setup_checklist(session, settings),
            "users": users,
        },
    )


@router.get("/settings/plumbing", response_class=HTMLResponse)
def plumbing_settings_page(
    request: Request,
    refresh: bool = False,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    credentials = load_credentials(settings)
    sources = session.exec(select(Source).order_by(Source.created_at)).all()
    active_provider = resolve_provider(
        credentials=credentials,
        settings_provider=settings.llm_provider,
        settings_model=settings.llm_model,
    )
    llm_models = list_chat_models(active_provider, credentials=credentials)
    configured_providers = available_providers(credentials)
    report = get_health_report(force_refresh=refresh)
    return templates.TemplateResponse(
        request,
        "settings_plumbing.html",
        {
            "user": user,
            "active": "settings",
            "settings_tab": "plumbing",
            "s": settings,
            "setup": _setup_checklist(session, settings),
            "credentials": credentials,
            "sources": sources,
            "report": report,
            "llm_models": llm_models,
            "llm_provider": active_provider.value,
            "llm_provider_options": [
                {
                    "id": provider.value,
                    "label": PROVIDER_LABELS[provider],
                    "configured": provider in configured_providers,
                    "default_model": DEFAULT_LLM_MODELS[provider],
                }
                for provider in LlmProviderId
            ],
        },
    )


@router.get("/settings/connections")
def connections_redirect():
    return RedirectResponse("/settings/plumbing", status_code=301)


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
    newsdata_api_key: str = Form(""),
    weatherapi_api_key: str = Form(""),
    clear_elevenlabs: str | None = Form(None),
    clear_speechify: str | None = Form(None),
    clear_openrouter: str | None = Form(None),
    clear_openai: str | None = Form(None),
    clear_anthropic: str | None = Form(None),
    clear_llm: str | None = Form(None),
    clear_zyte: str | None = Form(None),
    clear_finnhub: str | None = Form(None),
    clear_newsdata: str | None = Form(None),
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
        newsdata_api_key=newsdata_api_key,
        weatherapi_api_key=weatherapi_api_key,
        clear_elevenlabs=clear_elevenlabs is not None,
        clear_speechify=clear_speechify is not None,
        clear_openrouter=clear_openrouter is not None,
        clear_openai=clear_openai is not None,
        clear_anthropic=clear_anthropic is not None,
        clear_llm=clear_llm is not None,
        clear_zyte=clear_zyte is not None,
        clear_finnhub=clear_finnhub is not None,
        clear_newsdata=clear_newsdata is not None,
        clear_weatherapi=clear_weatherapi is not None,
    )
    settings.updated_at = utcnow()
    session.add(settings)
    session.commit()
    return RedirectResponse("/settings/plumbing?msg=Keys+saved.+The+health+checks+below+will+confirm+everything+connects.", status_code=303)


@router.get("/settings/status")
def status_redirect():
    return RedirectResponse("/settings/plumbing#health", status_code=301)


@router.get("/api/health")
def health_status_api(
    refresh: bool = False,
    user: User = Depends(web_user),
):
    return JSONResponse(get_health_report(force_refresh=refresh).to_dict())


@router.get("/settings/advanced")
def advanced_redirect():
    return RedirectResponse("/settings", status_code=301)


@router.get("/api/locations/search")
def location_search(
    q: str = Query(""),
    user: User = Depends(web_user),
):
    results = weather.search_locations(q)
    payload = []
    for result in results:
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
    return JSONResponse(
        [{"id": model.id, "label": model.label} for model in models[:25]]
    )


@router.get("/api/tts/voices")
def tts_voice_options_api(
    provider: str = Query(""),
    voice_language: str = Query(""),
    voice_accent: str = Query(""),
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    credentials = load_credentials(settings)
    provider_id = resolve_tts_provider(
        credentials=credentials,
        settings_provider=provider.strip() or settings.tts_provider,
    )
    language = voice_language.strip().lower()
    accent = voice_accent.strip().lower()
    voices: list = []
    accents: list[str] = []
    if provider_id in available_tts_providers(credentials):
        try:
            tts = get_provider(
                credentials=credentials, settings_provider=provider_id.value
            )
            voices = list_voice_options(
                tts,
                voice_language=language,
                voice_accent=accent,
                news_hl=settings.news_hl,
            )
            accents = list_accent_options(
                tts,
                voice_language=language,
                news_hl=settings.news_hl,
            )
        except Exception as error:
            logger.info("Voice listing unavailable: %s", error)

    return JSONResponse(
        {
            "provider": provider_id.value,
            "configured": provider_id in available_tts_providers(credentials),
            "voices": [
                {
                    "voice_id": voice.voice_id,
                    "name": voice.name,
                    "accent": voice.accent,
                    "preview_url": voice.preview_url,
                }
                for voice in voices
            ],
            "accents": accents,
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
    return llm_model_search(provider=LlmProviderId.openrouter.value, q=q, user=user, session=session)


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
    weather_enabled: str | None = Form(None),
    weather_provider: str = Form("open_meteo"),
):
    settings = get_settings(session)

    hour, minute = _parse_time(schedule_time)
    settings.schedule_hour = hour
    settings.schedule_minute = minute

    timezone_name = timezone.strip() or "UTC"
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return RedirectResponse(
            "/settings?err=That+time+zone+isn't+recognised.+It+fills+in+automatically+when+you+pick+your+town+from+the+list.",
            status_code=303,
        )

    address = address.strip()
    if address:
        if location_confirmed != "1" or not latitude or not longitude or not locality:
            return RedirectResponse(
                "/settings?err=Choose+your+town+from+the+list+before+saving.",
                status_code=303,
            )
        try:
            settings.latitude = float(latitude)
            settings.longitude = float(longitude)
        except ValueError:
            return RedirectResponse(
                "/settings?err=That+town+didn't+save.+Select+one+from+the+list+and+try+again.",
                status_code=303,
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
    settings.weather_enabled = weather_enabled is not None
    resolved_provider = resolve_weather_provider(weather_provider)
    settings.weather_provider = resolved_provider.value
    settings.updated_at = utcnow()

    session.add(settings)
    session.commit()
    reschedule()
    return RedirectResponse("/settings?msg=Schedule+and+location+saved.+The+next+episode+will+use+these+settings.", status_code=303)


@router.post("/settings/calendar")
def save_calendar(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    calendar_url: str = Form(""),
):
    settings = get_settings(session)
    settings.calendar_url = calendar_url.strip()
    settings.updated_at = utcnow()
    session.add(settings)
    session.commit()
    return RedirectResponse("/settings/household?msg=Calendar+link+saved.", status_code=303)


@router.post("/settings/stocks")
def save_stocks_settings(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    stocks_enabled: str | None = Form(None),
    stocks_mature_reactions: str | None = Form(None),
):
    settings = get_settings(session)
    settings.stocks_enabled = stocks_enabled is not None
    settings.stocks_mature_reactions = stocks_mature_reactions is not None
    settings.updated_at = utcnow()
    session.add(settings)
    session.commit()
    return RedirectResponse("/settings?msg=Stock+watch+settings+saved.", status_code=303)


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
        return RedirectResponse(
            "/settings?err=Enter+at+least+one+ticker+symbol.",
            status_code=303,
        )

    existing_symbols = {
        item.symbol for item in session.exec(select(WatchlistItem)).all()
    }
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
            return RedirectResponse(
                "/settings?err=Enter+valid+ticker+symbols+(e.g.+AAPL+or+%5EGSPC).",
                status_code=303,
            )
        if duplicates and not invalid:
            err = (
                "That+ticker+is+already+on+your+watchlist."
                if len(symbols) == 1
                else "Those+tickers+are+already+on+your+watchlist."
            )
            return RedirectResponse(f"/settings?err={err}", status_code=303)
        return RedirectResponse(
            "/settings?err=No+new+stocks+added.+Check+ticker+symbols+and+try+again.",
            status_code=303,
        )

    message = (
        "Stock+added+to+watchlist."
        if len(added) == 1
        else f"{len(added)}+stocks+added+to+watchlist."
    )
    extras: list[str] = []
    if invalid:
        extras.append(f"skipped+invalid:+{quote_plus(', '.join(invalid))}")
    if duplicates:
        extras.append(f"already+listed:+{quote_plus(', '.join(duplicates))}")
    if extras:
        message += "+(" + ";+".join(extras) + ")"
    return RedirectResponse(f"/settings?msg={message}", status_code=303)


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
    return RedirectResponse("/settings?msg=Stock+removed+from+watchlist.", status_code=303)


@router.post("/settings/story-mix")
def save_story_mix_settings(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    preferred_categories: list[str] = Form(default=[]),
):
    settings = get_settings(session)
    settings.preferred_categories = serialize_selected(preferred_categories)
    settings.updated_at = utcnow()
    session.add(settings)
    session.commit()
    return RedirectResponse("/settings?msg=Story+mix+saved.", status_code=303)


@router.post("/settings/voice")
def save_voice_settings(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    tts_provider: str = Form(""),
    voice_id: str = Form(""),
    voice_model: str = Form("eleven_v3"),
    voice_language: str = Form(""),
    voice_accent: str = Form(""),
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

    message = "Narrator+voice+saved."
    if new_provider != previous_provider:
        # The submitted voice/model belong to the old service — start from the
        # new service's defaults and let the reloaded page offer its voices.
        settings.voice_id = DEFAULT_VOICE_IDS[new_provider]
        settings.voice_model = DEFAULT_VOICE_MODELS[new_provider]
        message = "Narration+service+changed.+Pick+a+voice+from+the+updated+list+below."
    else:
        settings.voice_id = voice_id.strip() or settings.voice_id
        settings.voice_model = normalize_voice_model(
            new_provider, voice_model.strip() or settings.voice_model
        )
    settings.voice_language = voice_language.strip().lower()
    settings.voice_accent = voice_accent.strip().lower()
    settings.voice_randomize = voice_randomize is not None
    if new_provider is TtsProviderId.speechify:
        settings.speechify_emotion = normalize_speechify_emotion(speechify_emotion)
    settings.updated_at = utcnow()
    session.add(settings)
    session.commit()
    return RedirectResponse(f"/settings?msg={message}#voice", status_code=303)


@router.post("/settings/episode-length")
def save_episode_length_settings(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    max_article_length: int = Form(6000),
    target_minutes_min: float = Form(1.5),
    target_minutes_max: float = Form(3.0),
):
    settings = get_settings(session)
    if target_minutes_max < target_minutes_min:
        return RedirectResponse(
            "/settings?err=The+longest+length+can't+be+shorter+than+the+shortest.+Swap+the+two+numbers+and+try+again.#length",
            status_code=303,
        )
    settings.max_article_length = max(500, max_article_length)
    settings.target_minutes_min = max(0.5, target_minutes_min)
    settings.target_minutes_max = target_minutes_max
    settings.updated_at = utcnow()
    session.add(settings)
    session.commit()
    return RedirectResponse("/settings?msg=Episode+length+saved.#length", status_code=303)


@router.post("/settings/podcast-app")
def save_podcast_app_settings(
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
    return RedirectResponse("/settings?msg=Podcast+details+saved.#podcast-app", status_code=303)


@router.post("/settings/writer")
def save_writer_settings(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    llm_provider: str = Form(""),
    llm_model: str = Form("openai/gpt-4o-mini"),
):
    settings = get_settings(session)
    try:
        provider_id = LlmProviderId((llm_provider or settings.llm_provider or resolve_provider(
            credentials=load_credentials(settings),
            settings_provider=settings.llm_provider,
            settings_model=settings.llm_model,
        )).strip().lower())
    except ValueError:
        provider_id = resolve_provider(
            credentials=load_credentials(settings),
            settings_provider=settings.llm_provider,
            settings_model=settings.llm_model,
        )
    settings.llm_provider = provider_id.value
    settings.llm_model = normalize_model(provider_id, llm_model.strip() or settings.llm_model)
    settings.updated_at = utcnow()
    session.add(settings)
    session.commit()
    return RedirectResponse("/settings/plumbing?msg=Script+writer+saved.#writer", status_code=303)


@router.post("/settings/intro")
async def save_intro(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    intro: UploadFile | None = File(None),
    intro_enabled: str | None = Form(None),
    intro_play_seconds: float = Form(6.0),
):
    settings = get_settings(session)
    settings.intro_enabled = intro_enabled is not None
    settings.intro_play_seconds = max(0.0, intro_play_seconds)
    settings.updated_at = utcnow()

    message = "Intro+settings+saved."
    if intro is not None and intro.filename:
        data = await intro.read()
        if not data:
            return RedirectResponse("/settings?err=That+file+was+empty.+Choose+a+different+MP3+and+try+again.#music", status_code=303)
        with open(config.intro_path, "wb") as handle:
            handle.write(data)
        message = "Intro+music+uploaded.+It+will+play+before+the+next+episode."

    session.add(settings)
    session.commit()
    return RedirectResponse(f"/settings?msg={message}#music", status_code=303)


@router.post("/settings/outro")
async def save_outro(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    outro: UploadFile | None = File(None),
    outro_enabled: str | None = Form(None),
    outro_play_seconds: float = Form(2.0),
):
    settings = get_settings(session)
    settings.outro_enabled = outro_enabled is not None
    settings.outro_play_seconds = max(0.0, outro_play_seconds)
    settings.updated_at = utcnow()

    message = "Outro+settings+saved."
    if outro is not None and outro.filename:
        data = await outro.read()
        if not data:
            return RedirectResponse("/settings?err=That+file+was+empty.+Choose+a+different+MP3+and+try+again.#music", status_code=303)
        with open(config.outro_path, "wb") as handle:
            handle.write(data)
        message = "Outro+music+uploaded.+It+will+play+after+the+next+episode."

    session.add(settings)
    session.commit()
    return RedirectResponse(f"/settings?msg={message}#music", status_code=303)


@router.post("/sources")
def add_source(
    url: str = Form(...),
    name: str = Form(""),
    priority: str | None = Form(None),
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    url = url.strip()
    message = "News+feed+added."
    if url:
        feed_url, is_feed = news.resolve_feed_url(url)
        if feed_url != url:
            message = quote_plus(f"News feed added — using the feed found at {feed_url}.")
        elif not is_feed:
            message = quote_plus(
                "Feed added, but that link doesn't look like an RSS feed "
                "and no feed was found on the page — it may return no stories."
            )
        session.add(Source(url=feed_url, name=name.strip(), priority=bool(priority)))
        session.commit()
    return RedirectResponse(f"/settings/plumbing?msg={message}#feeds", status_code=303)


@router.post("/sources/{source_id}/priority")
def toggle_source_priority(
    source_id: int,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    source = session.get(Source, source_id)
    message = "News+feed+not+found."
    if source is not None:
        source.priority = not source.priority
        session.add(source)
        session.commit()
        message = (
            "Feed+stories+will+always+be+included."
            if source.priority
            else "Feed+returned+to+normal+priority."
        )
    return RedirectResponse(f"/settings/plumbing?msg={message}#feeds", status_code=303)


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
    return RedirectResponse("/settings/plumbing?msg=News+feed+deleted.#feeds", status_code=303)


@router.post("/preferences")
def add_preference(
    topic: str = Form(...),
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    topics = _split_comma_list(topic)
    if not topics:
        return RedirectResponse(
            "/settings?err=Enter+at+least+one+topic.",
            status_code=303,
        )

    existing_topics = {
        preference.topic.casefold()
        for preference in session.exec(select(Preference)).all()
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
        err = (
            "That+topic+is+already+on+the+skip+list."
            if len(topics) == 1
            else "Those+topics+are+already+on+the+skip+list."
        )
        return RedirectResponse(f"/settings?err={err}", status_code=303)

    message = (
        "Topic+added+to+the+skip+list."
        if len(added) == 1
        else f"{len(added)}+topics+added+to+the+skip+list."
    )
    skipped = len(topics) - len(added)
    if skipped:
        message += f"+({skipped}+already+listed)"
    return RedirectResponse(f"/settings?msg={message}", status_code=303)


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
    return RedirectResponse("/settings?msg=Topic+removed+from+the+skip+list.", status_code=303)


@router.post("/users")
def add_user(
    username: str = Form(...),
    password: str = Form(...),
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    username = username.strip()
    if not username or not password:
        return RedirectResponse("/settings/household?err=Enter+a+username+and+password+for+the+new+person.", status_code=303)
    existing = session.exec(select(User).where(User.username == username)).first()
    if existing is not None:
        return RedirectResponse("/settings/household?err=That+username+is+already+in+use.+Try+a+different+one.", status_code=303)
    create_user(session, username, password)
    return RedirectResponse("/settings/household?msg=Household+member+added.", status_code=303)


def _safe_list_voices(settings, credentials):
    try:
        return list_voice_options(
            get_provider(credentials=credentials, settings_provider=settings.tts_provider),
            voice_language=settings.voice_language,
            voice_accent=settings.voice_accent,
            news_hl=settings.news_hl,
        )
    except Exception as error:
        logger.info("Voice listing unavailable: %s", error)
        return []


def _safe_list_accents(settings, credentials):
    try:
        return list_accent_options(
            get_provider(credentials=credentials, settings_provider=settings.tts_provider),
            voice_language=settings.voice_language,
            news_hl=settings.news_hl,
        )
    except Exception as error:
        logger.info("Accent listing unavailable: %s", error)
        return []


def _parse_time(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = max(0, min(23, int(hour_text)))
        minute = max(0, min(59, int(minute_text)))
        return hour, minute
    except (ValueError, AttributeError):
        return 7, 0
