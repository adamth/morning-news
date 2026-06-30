"""System health checks for deployment diagnostics and the settings status page."""

from __future__ import annotations

import hashlib
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable

import httpx
from sqlmodel import Session, select, text

from .config import config, env_str
from .db import HealthCheckCache, Settings, Source, WatchlistItem, engine, get_settings, utcnow
from .sources.calendar import _try_http_ics
from .sources.news import build_google_news_url
from .sources import stocks

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 12.0
_PASS_CACHE_TTL = timedelta(days=7)

_API_KEY_CHECKS: dict[str, str] = {
    "elevenlabs": "ELEVENLABS_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "zyte": "ZYTE_API_KEY",
    "finnhub": "FINNHUB_API_KEY",
}

_stored_report: HealthReport | None = None


class CheckStatus(str, Enum):
    ok = "ok"
    error = "error"
    unconfigured = "unconfigured"
    skipped = "skipped"


@dataclass
class HealthCheck:
    id: str
    name: str
    description: str
    group: str
    status: CheckStatus
    detail: str = ""
    required: bool = True


@dataclass
class HealthReport:
    checks: list[HealthCheck] = field(default_factory=list)
    checked_at: float | None = None

    @property
    def has_issues(self) -> bool:
        return self.issue_count > 0

    @property
    def issue_count(self) -> int:
        return sum(1 for check in self.checks if _check_is_issue(check))

    @property
    def groups(self) -> list[tuple[str, list[HealthCheck]]]:
        order = ("system", "api_keys", "services", "content")
        labels = {
            "system": "On this server",
            "api_keys": "Connections",
            "services": "Online services",
            "content": "Your show",
        }
        grouped: dict[str, list[HealthCheck]] = {key: [] for key in order}
        for check in self.checks:
            grouped.setdefault(check.group, []).append(check)
        return [(labels[key], grouped[key]) for key in order if grouped[key]]

    def to_dict(self) -> dict:
        return {
            "checked_at": self.checked_at,
            "has_issues": self.has_issues,
            "issue_count": self.issue_count,
            "checks": [
                {
                    "id": check.id,
                    "name": check.name,
                    "description": check.description,
                    "group": check.group,
                    "status": check.status.value,
                    "detail": check.detail,
                    "required": check.required,
                }
                for check in self.checks
            ],
        }


def _check_is_issue(check: HealthCheck) -> bool:
    if check.status == CheckStatus.error:
        return True
    if check.status == CheckStatus.unconfigured and check.required:
        return True
    return False


def _key_fingerprint(env_name: str) -> str:
    value = env_str(env_name)
    if not value:
        return ""
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _format_cached_detail(detail: str, checked_at: datetime) -> str:
    return f"{detail} (last verified {checked_at.strftime('%b %d')})"


def _get_valid_pass_cache(session: Session, check_id: str) -> HealthCheckCache | None:
    env_name = _API_KEY_CHECKS.get(check_id)
    if env_name is None:
        return None

    row = session.get(HealthCheckCache, check_id)
    if row is None or row.status != CheckStatus.ok.value:
        return None
    if row.key_fingerprint != _key_fingerprint(env_name):
        return None
    if utcnow() - row.checked_at > _PASS_CACHE_TTL:
        return None
    return row


def _update_pass_cache(session: Session, check_id: str, check: HealthCheck) -> None:
    if check_id not in _API_KEY_CHECKS:
        return

    existing = session.get(HealthCheckCache, check_id)
    if check.status == CheckStatus.ok:
        env_name = _API_KEY_CHECKS[check_id]
        row = existing or HealthCheckCache(check_id=check_id)
        row.status = check.status.value
        row.detail = check.detail
        row.checked_at = utcnow()
        row.key_fingerprint = _key_fingerprint(env_name)
        session.add(row)
    elif existing is not None:
        session.delete(existing)


def _run_cached_api_key_check(
    session: Session,
    *,
    force_all: bool,
    check_id: str,
    name: str,
    description: str,
    required: bool,
    probe: Callable[[], tuple[CheckStatus, str]],
) -> HealthCheck:
    if not force_all:
        cached = _get_valid_pass_cache(session, check_id)
        if cached is not None:
            return HealthCheck(
                id=check_id,
                name=name,
                description=description,
                group="api_keys",
                status=CheckStatus.ok,
                detail=_format_cached_detail(cached.detail, cached.checked_at),
                required=required,
            )

    check = _run_check(
        check_id=check_id,
        name=name,
        description=description,
        group="api_keys",
        required=required,
        probe=probe,
    )
    _update_pass_cache(session, check_id, check)
    return check


def _run_check(
    *,
    check_id: str,
    name: str,
    description: str,
    group: str,
    required: bool,
    probe: Callable[[], tuple[CheckStatus, str]],
) -> HealthCheck:
    try:
        status, detail = probe()
    except Exception as error:  # pragma: no cover - defensive guard for probes
        logger.exception("Health probe %s raised unexpectedly", check_id)
        status, detail = CheckStatus.error, str(error)
    return HealthCheck(
        id=check_id,
        name=name,
        description=description,
        group=group,
        status=status,
        detail=detail,
        required=required,
    )


def _probe_database() -> tuple[CheckStatus, str]:
    with Session(engine) as session:
        session.exec(text("SELECT 1")).one()
    return CheckStatus.ok, "Database is reachable"


def _probe_data_storage() -> tuple[CheckStatus, str]:
    test_path = config.data_dir / ".health_write_test"
    try:
        config.ensure_dirs()
        test_path.write_text("ok")
        test_path.unlink(missing_ok=True)
    except OSError as error:
        return CheckStatus.error, f"Cannot write to {config.data_dir}: {error}"
    return CheckStatus.ok, "Storage is writable"


def _probe_ffmpeg() -> tuple[CheckStatus, str]:
    binary = shutil.which("ffmpeg")
    if binary is None:
        return CheckStatus.error, "ffmpeg is not installed — audio cannot be assembled"
    return CheckStatus.ok, "Audio tools are available"


def _probe_elevenlabs() -> tuple[CheckStatus, str]:
    api_key = env_str("ELEVENLABS_API_KEY")
    if not api_key:
        return CheckStatus.unconfigured, "Add ELEVENLABS_API_KEY to your server environment (.env or container settings)"
    try:
        # Use /v1/voices, not /v1/user — restricted keys scoped to TTS return 401 on user endpoints
        # but work fine for voice listing and synthesis (what Morning News actually needs).
        response = httpx.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": api_key},
            timeout=_HTTP_TIMEOUT,
        )
        if response.status_code == 401:
            return CheckStatus.error, "Narration API key was rejected — check ELEVENLABS_API_KEY"
        response.raise_for_status()
        voice_count = len(response.json().get("voices") or [])
    except httpx.HTTPError as error:
        return CheckStatus.error, f"Could not reach the narration service: {error}"
    except ValueError as error:
        return CheckStatus.error, f"Unexpected response from narration service: {error}"
    return CheckStatus.ok, f"Connected — {voice_count} voices available"


def _probe_openrouter() -> tuple[CheckStatus, str]:
    api_key = env_str("OPENROUTER_API_KEY")
    if not api_key:
        return CheckStatus.unconfigured, "Add OPENROUTER_API_KEY to your server environment (.env or container settings)"
    try:
        response = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_HTTP_TIMEOUT,
        )
        if response.status_code == 401:
            return CheckStatus.error, "Script-writing API key was rejected — check OPENROUTER_API_KEY"
        response.raise_for_status()
        models = response.json().get("data") or []
        if not models:
            return CheckStatus.error, "Connected but no writing models were returned"
    except httpx.HTTPError as error:
        return CheckStatus.error, f"Could not reach the script-writing service: {error}"
    except ValueError as error:
        return CheckStatus.error, f"Unexpected response from script-writing service: {error}"
    return CheckStatus.ok, "Connected and ready"


def _probe_zyte() -> tuple[CheckStatus, str]:
    api_key = env_str("ZYTE_API_KEY")
    if not api_key:
        return (
            CheckStatus.skipped,
            "Optional — article extraction falls back to plain HTTP when unset",
        )
    try:
        response = httpx.post(
            "https://api.zyte.com/v1/extract",
            auth=(api_key, ""),
            json={"url": "https://example.com", "httpResponseBody": True},
            timeout=_HTTP_TIMEOUT,
        )
        if response.status_code == 401:
            return CheckStatus.error, "API key was rejected (401 Unauthorized)"
        if response.status_code >= 500:
            return CheckStatus.error, f"Zyte returned server error {response.status_code}"
    except httpx.HTTPError as error:
        return CheckStatus.error, f"Could not reach Zyte: {error}"
    return CheckStatus.ok, "Connected and authenticated"


def _probe_newsdata() -> tuple[CheckStatus, str]:
    if not env_str("NEWSDATA_API_KEY"):
        return (
            CheckStatus.skipped,
            "Optional — not used by this app yet",
        )
    return (
        CheckStatus.skipped,
        "Key is set but NewsData.io is not wired into the pipeline yet",
    )


def _probe_open_meteo_geocoding() -> tuple[CheckStatus, str]:
    try:
        response = httpx.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": "London", "count": 1},
            timeout=_HTTP_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        return CheckStatus.error, f"Could not reach Open-Meteo geocoding: {error}"
    return CheckStatus.ok, "Geocoding API is reachable"


def _probe_open_meteo_forecast(settings: Settings) -> tuple[CheckStatus, str]:
    if not settings.weather_enabled:
        return CheckStatus.skipped, "Weather is turned off on Settings → Basic"
    if settings.latitude is None or settings.longitude is None:
        return CheckStatus.skipped, "Add your town on Settings → Basic to enable weather checks"
    try:
        response = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": settings.latitude,
                "longitude": settings.longitude,
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "timezone": settings.timezone or "UTC",
            },
            timeout=_HTTP_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        return CheckStatus.error, f"Could not reach Open-Meteo forecast: {error}"
    return CheckStatus.ok, "Forecast API is reachable for your location"


def _probe_location(settings: Settings) -> tuple[CheckStatus, str]:
    if settings.latitude is not None and settings.locality.strip():
        return CheckStatus.ok, f"Using {settings.locality.strip()}"
    return (
        CheckStatus.unconfigured,
        "Pick your town on Settings → Basic before episodes can use weather and local news",
    )


def _probe_google_news(settings: Settings) -> tuple[CheckStatus, str]:
    if not settings.locality.strip():
        return CheckStatus.skipped, "Add your town on Settings → Basic to enable local headlines"
    feed_url = build_google_news_url(
        settings.locality,
        settings.news_hl,
        settings.news_gl,
        settings.news_ceid,
    )
    if feed_url is None:
        return CheckStatus.skipped, "No Google News feed URL could be built"
    try:
        response = httpx.get(
            feed_url,
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "MorningNewsHealthCheck/1.0"},
        )
        response.raise_for_status()
        body = response.text[:500].lower()
        if "this feed is not available" in body:
            return CheckStatus.error, "No local headlines are available for this town right now"
    except httpx.HTTPError as error:
        return CheckStatus.error, f"Could not fetch Google News feed: {error}"
    return CheckStatus.ok, "Local headlines are reachable"


def _probe_calendar(settings: Settings) -> tuple[CheckStatus, str]:
    calendar_url = settings.calendar_url.strip()
    if not calendar_url:
        return CheckStatus.skipped, "Optional — add a shared calendar link on Settings → Basic"
    ical_text = _try_http_ics(calendar_url)
    if ical_text:
        return CheckStatus.ok, "Calendar link returned events"
    return (
        CheckStatus.error,
        "Could not read that calendar link — try a direct subscription URL (often ends in .ics)",
    )


def _probe_finnhub() -> tuple[CheckStatus, str]:
    api_key = env_str("FINNHUB_API_KEY")
    if not api_key:
        return (
            CheckStatus.unconfigured,
            "Required for stock watch — free key at finnhub.io",
        )
    try:
        response = httpx.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": "AAPL", "token": api_key},
            timeout=_HTTP_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("c") in (None, 0):
            return CheckStatus.error, "Finnhub responded but returned no quote data"
    except httpx.HTTPError as error:
        return CheckStatus.error, f"Could not reach Finnhub: {error}"
    return CheckStatus.ok, "Connected and returning quotes"


def _probe_stocks(session: Session, settings: Settings) -> tuple[CheckStatus, str]:
    if not settings.stocks_enabled:
        return CheckStatus.skipped, "Stock watch is turned off on Settings → Basic"
    items = session.exec(
        select(WatchlistItem).where(WatchlistItem.enabled == True)  # noqa: E712
    ).all()
    if not items:
        return CheckStatus.skipped, "Add tickers on Settings → Basic to enable stock checks"
    if not env_str("FINNHUB_API_KEY"):
        return (
            CheckStatus.error,
            "Set FINNHUB_API_KEY in your environment — Yahoo Finance is often rate-limited",
        )
    summary = stocks.get_market_summary([items[0].symbol])
    if summary is None:
        return CheckStatus.error, "Could not fetch a quote — check FINNHUB_API_KEY and your tickers"
    return CheckStatus.ok, f"Quotes are reachable (checked {items[0].symbol})"


def _probe_rss_feed(source: Source) -> tuple[CheckStatus, str]:
    label = source.name.strip() or source.url
    try:
        response = httpx.get(
            source.url,
            timeout=_HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "MorningNewsHealthCheck/1.0"},
        )
        response.raise_for_status()
        body = response.text[:2000].lower()
        if "<rss" not in body and "<feed" not in body and "application/rss" not in body:
            return CheckStatus.error, "That link responded but does not look like a news feed"
    except httpx.HTTPError as error:
        return CheckStatus.error, f"Could not fetch feed: {error}"
    return CheckStatus.ok, f"Feed is reachable ({label})"


def run_liveness_checks() -> HealthReport:
    """Fast checks for Docker /healthz — no external API calls."""

    checks = [
        _run_check(
            check_id="database",
            name="App data",
            description="Stores your settings and episode history",
            group="system",
            required=True,
            probe=_probe_database,
        ),
        _run_check(
            check_id="data_storage",
            name="Episode storage",
            description="Where finished episodes and uploads are saved",
            group="system",
            required=True,
            probe=_probe_data_storage,
        ),
        _run_check(
            check_id="ffmpeg",
            name="Audio assembly",
            description="Combines narration, intro/outro music, and final MP3",
            group="system",
            required=True,
            probe=_probe_ffmpeg,
        ),
    ]
    return HealthReport(checks=checks)


def run_health_checks(session: Session, *, force_all: bool = False) -> HealthReport:
    """Full dependency checks for the settings status page."""

    settings = get_settings(session)
    sources = session.exec(
        select(Source).where(Source.enabled == True).order_by(Source.created_at)  # noqa: E712
    ).all()

    checks: list[HealthCheck] = [
        *run_liveness_checks().checks,
        _run_cached_api_key_check(
            session,
            force_all=force_all,
            check_id="elevenlabs",
            name="Episode narration",
            description="Turns the written script into spoken audio",
            required=True,
            probe=_probe_elevenlabs,
        ),
        _run_cached_api_key_check(
            session,
            force_all=force_all,
            check_id="openrouter",
            name="Script writing",
            description="Chooses stories and writes each morning's script",
            required=True,
            probe=_probe_openrouter,
        ),
        _run_cached_api_key_check(
            session,
            force_all=force_all,
            check_id="zyte",
            name="Hard-to-read articles",
            description="Optional backup when a news site blocks normal fetching",
            required=False,
            probe=_probe_zyte,
        ),
        _run_cached_api_key_check(
            session,
            force_all=force_all,
            check_id="finnhub",
            name="Stock quotes",
            description="24-hour price changes for your watchlist",
            required=False,
            probe=_probe_finnhub,
        ),
        _run_check(
            check_id="newsdata",
            name="NewsData.io",
            description="Optional — not used by Morning News yet",
            group="api_keys",
            required=False,
            probe=_probe_newsdata,
        ),
        _run_check(
            check_id="location",
            name="Your town",
            description="Weather, local headlines, and time zone",
            group="content",
            required=True,
            probe=lambda: _probe_location(settings),
        ),
        _run_check(
            check_id="open_meteo_geocoding",
            name="Town search",
            description="Finds your town when you edit settings",
            group="services",
            required=False,
            probe=_probe_open_meteo_geocoding,
        ),
        _run_check(
            check_id="open_meteo_forecast",
            name="Weather forecast",
            description="Tomorrow's weather in your episode",
            group="services",
            required=False,
            probe=lambda: _probe_open_meteo_forecast(settings),
        ),
        _run_check(
            check_id="google_news",
            name="Local headlines",
            description="News stories for your area",
            group="services",
            required=False,
            probe=lambda: _probe_google_news(settings),
        ),
        _run_check(
            check_id="calendar",
            name="Family calendar",
            description="Today's events mentioned in the episode",
            group="content",
            required=False,
            probe=lambda: _probe_calendar(settings),
        ),
        _run_check(
            check_id="stocks",
            name="Stock watch",
            description="24-hour performance for your watchlist",
            group="services",
            required=False,
            probe=lambda: _probe_stocks(session, settings),
        ),
    ]

    for source in sources:
        checks.append(
            _run_check(
                check_id=f"rss_{source.id}",
                name=source.name.strip() or "Extra news feed",
                description=source.url,
                group="content",
                required=False,
                probe=lambda source=source: _probe_rss_feed(source),
            )
        )

    session.commit()
    return HealthReport(checks=checks)


def refresh_health_report(*, force_all: bool = False) -> HealthReport:
    """Run dependency checks and store the result for the UI."""

    global _stored_report
    with Session(engine) as session:
        report = run_health_checks(session, force_all=force_all)
    report.checked_at = time.time()
    _stored_report = report
    log_health_issues(report)
    return report


def get_health_report(*, force_refresh: bool = False) -> HealthReport:
    """Return the last scheduled health report without re-running checks."""

    if force_refresh:
        return refresh_health_report(force_all=True)
    if _stored_report is not None:
        return _stored_report
    return HealthReport()


def log_health_issues(report: HealthReport) -> None:
    """Log actionable health problems at startup."""

    for check in report.checks:
        if not _check_is_issue(check):
            continue
        logger.warning("Health check: %s — %s (%s)", check.name, check.detail, check.status.value)
