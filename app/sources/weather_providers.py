"""Weather forecast providers — WeatherAPI.com or Open-Meteo."""

from __future__ import annotations

import logging
from datetime import date, datetime
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from ..episode_log import LogTimer, active_log
from ..http_retry import httpx_request_with_retry

logger = logging.getLogger(__name__)

WEATHERAPI_FORECAST_URL = "https://api.weatherapi.com/v1/forecast.json"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# https://open-meteo.com/en/docs WMO weather interpretation codes.
OPEN_METEO_WEATHER_CODES: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snow",
    73: "moderate snow",
    75: "heavy snow",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


class WeatherProviderId(str, Enum):
    weatherapi = "weatherapi"
    open_meteo = "open_meteo"


WEATHER_PROVIDER_LABELS: dict[WeatherProviderId, str] = {
    WeatherProviderId.weatherapi: "WeatherAPI.com",
    WeatherProviderId.open_meteo: "Open-Meteo",
}


def weatherapi_configured(weatherapi_api_key: str | None) -> bool:
    return bool(weatherapi_api_key and weatherapi_api_key.strip())


def parse_weather_provider(value: str | None) -> WeatherProviderId | None:
    if not value or not value.strip():
        return None
    normalized = value.strip().lower()
    if normalized == "metno":
        return WeatherProviderId.open_meteo
    try:
        return WeatherProviderId(normalized)
    except ValueError:
        return None


def resolve_weather_provider(settings_provider: str = "") -> WeatherProviderId:
    explicit = parse_weather_provider(settings_provider)
    if explicit is not None:
        return explicit
    return WeatherProviderId.open_meteo


def _resolve_timezone(timezone: str) -> ZoneInfo:
    name = (timezone or "UTC").strip()
    if not name or name == "auto":
        name = "UTC"
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def fetch_open_meteo_forecast(
    latitude: float,
    longitude: float,
    timezone: str = "auto",
) -> tuple[str, float | None, float | None] | None:
    timer = LogTimer.start()
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": timezone,
        "forecast_days": 1,
    }
    try:
        response = httpx_request_with_retry(
            lambda: httpx.get(OPEN_METEO_FORECAST_URL, params=params, timeout=20)
        )
        response.raise_for_status()
        daily = (response.json().get("daily") or {})
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Open-Meteo weather lookup failed: %s", error)
        audit = active_log()
        if audit is not None:
            audit.record(
                "weather",
                "Open-Meteo forecast API",
                status="error",
                request={"url": OPEN_METEO_FORECAST_URL, "params": params},
                response={"error": str(error)},
                duration_ms=timer.elapsed_ms(),
            )
        return None

    audit = active_log()
    if audit is not None:
        audit.record(
            "weather",
            "Open-Meteo forecast API",
            request={"url": OPEN_METEO_FORECAST_URL, "params": params},
            response={"daily": daily},
            duration_ms=timer.elapsed_ms(),
        )
    if not daily.get("time"):
        return None

    code = (daily.get("weather_code") or [0])[0]
    temp_max = (daily.get("temperature_2m_max") or [None])[0]
    temp_min = (daily.get("temperature_2m_min") or [None])[0]
    precip = (daily.get("precipitation_probability_max") or [None])[0]
    condition = OPEN_METEO_WEATHER_CODES.get(int(code), "variable conditions")

    parts = [condition]
    if temp_max is not None and temp_min is not None:
        parts.append(f"a high of {round(temp_max)}\u00b0 and a low of {round(temp_min)}\u00b0")
    if precip is not None and precip >= 30:
        parts.append(f"{int(precip)}% chance of precipitation")

    return ", ".join(parts), temp_max, temp_min


def _summarize_weatherapi_day(day: dict) -> tuple[str, float | None, float | None]:
    temp_max = day.get("maxtemp_c")
    temp_min = day.get("mintemp_c")
    condition = ((day.get("condition") or {}).get("text") or "variable conditions").strip().lower()

    parts = [condition]
    if temp_max is not None and temp_min is not None:
        parts.append(f"a high of {round(temp_max)}\u00b0 and a low of {round(temp_min)}\u00b0")

    precip = day.get("daily_chance_of_rain")
    if precip is not None and int(precip) >= 30:
        parts.append(f"{int(precip)}% chance of rain")

    return ", ".join(parts), temp_max, temp_min


def _weatherapi_day_for_today(forecast_days: list[dict], timezone: str) -> dict | None:
    if not forecast_days:
        return None

    zone = _resolve_timezone(timezone)
    today = datetime.now(zone).date()
    for entry in forecast_days:
        date_text = entry.get("date")
        if not date_text:
            continue
        try:
            if date.fromisoformat(str(date_text)) == today:
                return entry.get("day") or {}
        except ValueError:
            continue

    return forecast_days[0].get("day") or {}


def fetch_weatherapi_forecast(
    latitude: float,
    longitude: float,
    timezone: str = "auto",
    *,
    api_key: str | None = None,
) -> tuple[str, float | None, float | None] | None:
    if not weatherapi_configured(api_key):
        logger.warning("WeatherAPI.com selected but no API key is configured")
        return None

    resolved_key = api_key.strip()
    timer = LogTimer.start()
    params = {
        "key": resolved_key,
        "q": f"{latitude},{longitude}",
        "days": 1,
        "aqi": "no",
        "alerts": "no",
    }
    try:
        response = httpx_request_with_retry(
            lambda: httpx.get(WEATHERAPI_FORECAST_URL, params=params, timeout=20)
        )
        response.raise_for_status()
        forecast_days = (response.json().get("forecast") or {}).get("forecastday") or []
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("WeatherAPI.com lookup failed: %s", error)
        audit = active_log()
        if audit is not None:
            audit.record(
                "weather",
                "WeatherAPI.com forecast API",
                status="error",
                request={"url": WEATHERAPI_FORECAST_URL, "params": {**params, "key": "[redacted]"}},
                response={"error": str(error)},
                duration_ms=timer.elapsed_ms(),
            )
        return None

    day = _weatherapi_day_for_today(forecast_days, timezone)
    if not day:
        return None

    summary = _summarize_weatherapi_day(day)
    audit = active_log()
    if audit is not None:
        audit.record(
            "weather",
            "WeatherAPI.com forecast API",
            request={"url": WEATHERAPI_FORECAST_URL, "params": {**params, "key": "[redacted]"}},
            response={"summary": summary[0]},
            duration_ms=timer.elapsed_ms(),
        )
    return summary


def fetch_forecast(
    provider: WeatherProviderId,
    latitude: float,
    longitude: float,
    timezone: str = "auto",
    *,
    weatherapi_api_key: str | None = None,
) -> tuple[str, float | None, float | None] | None:
    if provider is WeatherProviderId.weatherapi:
        return fetch_weatherapi_forecast(
            latitude,
            longitude,
            timezone,
            api_key=weatherapi_api_key,
        )
    return fetch_open_meteo_forecast(latitude, longitude, timezone)
