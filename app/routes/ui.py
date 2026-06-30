"""Dashboard, episode pages, and settings management."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlmodel import Session, select

from ..auth import create_user, web_user
from ..audio import probe_duration
from ..config import config
from ..db import (
    Episode,
    EpisodeArticle,
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
from ..health import get_health_report
from ..news_categories import NEWS_CATEGORIES, parse_selected, serialize_selected
from ..openrouter_models import list_chat_models
from ..pipeline import generate_episode_background
from ..scheduler import reschedule
from ..sources import weather
from ..templating import templates
from ..tts import get_provider
from ..urls import resolve_base_url

logger = logging.getLogger(__name__)
router = APIRouter()


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
            "media_url": media_url,
        },
    )


@router.post("/generate")
def generate_now(
    background_tasks: BackgroundTasks,
    user: User = Depends(web_user),
):
    background_tasks.add_task(generate_episode_background)
    return RedirectResponse("/?msg=Generating+episode+in+the+background", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    sources = session.exec(select(Source).order_by(Source.created_at)).all()
    preferences = session.exec(select(Preference).order_by(Preference.created_at)).all()
    watchlist = session.exec(select(WatchlistItem).order_by(WatchlistItem.created_at)).all()
    users = session.exec(select(User).order_by(User.created_at)).all()
    intro_duration = (
        probe_duration(config.intro_path) if config.intro_path.exists() else None
    )
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "active": "settings",
            "settings_tab": "basic",
            "s": settings,
            "sources": sources,
            "preferences": preferences,
            "watchlist": watchlist,
            "users": users,
            "intro_exists": config.intro_path.exists(),
            "intro_duration": intro_duration,
        },
    )


@router.get("/settings/status", response_class=HTMLResponse)
def settings_status_page(
    request: Request,
    refresh: bool = False,
    user: User = Depends(web_user),
):
    report = get_health_report(force_refresh=refresh)
    return templates.TemplateResponse(
        request,
        "settings_status.html",
        {
            "user": user,
            "active": "settings",
            "settings_tab": "status",
            "report": report,
        },
    )


@router.get("/api/health")
def health_status_api(
    refresh: bool = False,
    user: User = Depends(web_user),
):
    return JSONResponse(get_health_report(force_refresh=refresh).to_dict())


@router.get("/settings/advanced", response_class=HTMLResponse)
def advanced_settings_page(
    request: Request,
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    settings = get_settings(session)
    voices = _safe_list_voices()
    openrouter_models = list_chat_models()
    return templates.TemplateResponse(
        request,
        "settings_advanced.html",
        {
            "user": user,
            "active": "settings",
            "settings_tab": "advanced",
            "s": settings,
            "voices": voices,
            "openrouter_models": openrouter_models,
            "news_categories": NEWS_CATEGORIES,
            "selected_categories": set(parse_selected(settings.preferred_categories)),
        },
    )


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


@router.get("/api/openrouter/models")
def openrouter_model_search(
    q: str = Query(""),
    user: User = Depends(web_user),
):
    query = q.strip().lower()
    models = list_chat_models()
    if query:
        models = [
            model
            for model in models
            if query in model.id.lower() or query in model.name.lower()
        ]
    return JSONResponse(
        [{"id": model.id, "label": model.label} for model in models[:25]]
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
    weather_enabled: str | None = Form(None),
):
    settings = get_settings(session)

    hour, minute = _parse_time(schedule_time)
    settings.schedule_hour = hour
    settings.schedule_minute = minute

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
        settings.timezone = timezone.strip() or "UTC"
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
    return RedirectResponse("/settings?msg=Calendar+link+saved.", status_code=303)


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

    normalized = stocks.normalize_symbol(symbol)
    if not normalized:
        return RedirectResponse(
            "/settings?err=Enter+a+valid+ticker+symbol+(e.g.+AAPL+or+%5EGSPC).",
            status_code=303,
        )
    existing = session.exec(
        select(WatchlistItem).where(WatchlistItem.symbol == normalized)
    ).first()
    if existing is not None:
        return RedirectResponse("/settings?err=That+ticker+is+already+on+your+watchlist.", status_code=303)
    session.add(WatchlistItem(symbol=normalized, label=label.strip()))
    session.commit()
    return RedirectResponse("/settings?msg=Stock+added+to+watchlist.", status_code=303)


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


@router.post("/settings/advanced")
def save_advanced_settings(
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
    preferred_categories: list[str] = Form(default=[]),
    max_article_length: int = Form(6000),
    target_minutes_min: float = Form(1.5),
    target_minutes_max: float = Form(3.0),
    voice_id: str = Form(""),
    voice_model: str = Form("eleven_v3"),
    openrouter_model: str = Form("openai/gpt-4o-mini"),
    podcast_title: str = Form("Morning News"),
    podcast_author: str = Form("Morning News"),
    podcast_description: str = Form(""),
):
    settings = get_settings(session)
    settings.preferred_categories = serialize_selected(preferred_categories)
    settings.max_article_length = max(500, max_article_length)
    settings.target_minutes_min = target_minutes_min
    settings.target_minutes_max = target_minutes_max
    settings.voice_id = voice_id.strip() or settings.voice_id
    settings.voice_model = voice_model.strip() or settings.voice_model
    settings.openrouter_model = openrouter_model.strip() or settings.openrouter_model
    settings.podcast_title = podcast_title.strip() or "Morning News"
    settings.podcast_author = podcast_author.strip() or "Morning News"
    settings.podcast_description = podcast_description.strip()
    settings.updated_at = utcnow()

    session.add(settings)
    session.commit()
    return RedirectResponse("/settings/advanced?msg=Advanced+settings+saved.", status_code=303)


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
            return RedirectResponse("/settings?err=That+file+was+empty.+Choose+a+different+MP3+and+try+again.", status_code=303)
        with open(config.intro_path, "wb") as handle:
            handle.write(data)
        message = "Intro+music+uploaded.+It+will+play+before+the+next+episode."

    session.add(settings)
    session.commit()
    return RedirectResponse(f"/settings?msg={message}", status_code=303)


@router.post("/sources")
def add_source(
    url: str = Form(...),
    name: str = Form(""),
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    url = url.strip()
    if url:
        session.add(Source(url=url, name=name.strip()))
        session.commit()
    return RedirectResponse("/settings?msg=News+feed+added.", status_code=303)


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
    return RedirectResponse("/settings?msg=News+feed+deleted.", status_code=303)


@router.post("/preferences")
def add_preference(
    topic: str = Form(...),
    user: User = Depends(web_user),
    session: Session = Depends(get_session),
):
    topic = topic.strip()
    if topic:
        session.add(Preference(topic=topic))
        session.commit()
    return RedirectResponse("/settings?msg=Topic+added+to+the+skip+list.", status_code=303)


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
        return RedirectResponse("/settings?err=Enter+a+username+and+password+for+the+new+person.", status_code=303)
    existing = session.exec(select(User).where(User.username == username)).first()
    if existing is not None:
        return RedirectResponse("/settings?err=That+username+is+already+in+use.+Try+a+different+one.", status_code=303)
    create_user(session, username, password)
    return RedirectResponse("/settings?msg=Household+member+added.", status_code=303)


def _safe_list_voices():
    try:
        return get_provider().list_voices()
    except Exception as error:
        logger.info("Voice listing unavailable: %s", error)
        return []


def _parse_time(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = max(0, min(23, int(hour_text)))
        minute = max(0, min(59, int(minute_text)))
        return hour, minute
    except (ValueError, AttributeError):
        return 7, 0
