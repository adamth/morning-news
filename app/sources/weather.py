"""Weather + geocoding via Open-Meteo (free, no API key)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# https://open-meteo.com/en/docs WMO weather interpretation codes.
WEATHER_CODES: dict[int, str] = {
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


@dataclass
class GeocodeResult:
    latitude: float
    longitude: float
    locality: str
    country_code: str
    timezone: str
    country: str = ""
    admin1: str = ""
    open_meteo_id: int | None = None

    @property
    def display_label(self) -> str:
        parts = [self.locality]
        if self.admin1 and self.admin1 != self.locality:
            parts.append(self.admin1)
        if self.country:
            parts.append(self.country)
        return ", ".join(parts)


def _parse_geocode_result(entry: dict) -> GeocodeResult:
    return GeocodeResult(
        latitude=entry["latitude"],
        longitude=entry["longitude"],
        locality=entry.get("name", ""),
        country_code=entry.get("country_code", ""),
        timezone=entry.get("timezone", "UTC"),
        country=entry.get("country", ""),
        admin1=entry.get("admin1", ""),
        open_meteo_id=entry.get("id"),
    )


def news_edition_for_country(country_code: str) -> tuple[str, str, str]:
    """Map ISO country code to Google News hl / gl / ceid defaults."""

    code = (country_code or "US").upper()
    defaults: dict[str, tuple[str, str, str]] = {
        "AU": ("en-AU", "AU", "AU:en"),
        "US": ("en-US", "US", "US:en"),
        "GB": ("en-GB", "GB", "GB:en"),
        "CA": ("en-CA", "CA", "CA:en"),
        "NZ": ("en-NZ", "NZ", "NZ:en"),
        "IE": ("en-IE", "IE", "IE:en"),
        "IN": ("en-IN", "IN", "IN:en"),
        "DE": ("de", "DE", "DE:de"),
        "FR": ("fr", "FR", "FR:fr"),
        "ES": ("es", "ES", "ES:es"),
        "IT": ("it", "IT", "IT:it"),
        "JP": ("ja", "JP", "JP:ja"),
    }
    if code in defaults:
        return defaults[code]
    return (f"en-{code}", code, f"{code}:en")


def search_locations(query: str, *, count: int = 8) -> list[GeocodeResult]:
    """Return location suggestions for autocomplete."""

    query = query.strip()
    if len(query) < 2:
        return []
    try:
        response = httpx.get(
            GEOCODE_URL,
            params={"name": query, "count": count, "language": "en", "format": "json"},
            timeout=20,
        )
        response.raise_for_status()
        results = response.json().get("results") or []
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Location search failed for %r: %s", query, error)
        return []
    return [_parse_geocode_result(entry) for entry in results]


def geocode(address: str) -> GeocodeResult | None:
    """Resolve an address/place name to coordinates and a locality name."""

    matches = search_locations(address, count=1)
    return matches[0] if matches else None


def resolve_location(
    *,
    locality: str,
    latitude: float | None = None,
    longitude: float | None = None,
    country_code: str = "",
) -> GeocodeResult | None:
    """Match a stored location to the best geocoder result using coordinates."""

    if not locality.strip():
        return None

    candidates = search_locations(locality.strip(), count=20)
    if not candidates:
        return None

    country = country_code.strip().upper()
    if country:
        filtered = [item for item in candidates if item.country_code.upper() == country]
        if filtered:
            candidates = filtered

    if latitude is not None and longitude is not None:
        candidates.sort(
            key=lambda item: (item.latitude - latitude) ** 2 + (item.longitude - longitude) ** 2
        )

    return candidates[0]


@dataclass
class WeatherSummary:
    text: str
    temperature_max: float | None = None
    temperature_min: float | None = None


def get_weather(latitude: float, longitude: float, timezone: str = "auto") -> WeatherSummary | None:
    """Return a short human-readable summary of today's weather."""

    try:
        response = httpx.get(
            FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": timezone,
                "forecast_days": 1,
            },
            timeout=20,
        )
        response.raise_for_status()
        daily = response.json().get("daily") or {}
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("Weather lookup failed: %s", error)
        return None
    if not daily.get("time"):
        return None

    code = (daily.get("weather_code") or [0])[0]
    temp_max = (daily.get("temperature_2m_max") or [None])[0]
    temp_min = (daily.get("temperature_2m_min") or [None])[0]
    precip = (daily.get("precipitation_probability_max") or [None])[0]
    condition = WEATHER_CODES.get(int(code), "variable conditions")

    parts = [f"{condition}"]
    if temp_max is not None and temp_min is not None:
        parts.append(f"a high of {round(temp_max)}\u00b0 and a low of {round(temp_min)}\u00b0")
    if precip is not None and precip >= 30:
        parts.append(f"{int(precip)}% chance of precipitation")
    return WeatherSummary(text=", ".join(parts), temperature_max=temp_max, temperature_min=temp_min)

