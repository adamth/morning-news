"""Location search via Open-Meteo; forecasts via WeatherAPI.com or Open-Meteo."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from .weather_providers import (
    WEATHER_PROVIDER_LABELS,
    WeatherProviderId,
    fetch_forecast,
    resolve_weather_provider,
)

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"


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


def get_weather(
    latitude: float,
    longitude: float,
    timezone: str = "auto",
    *,
    provider: str = "",
    weatherapi_api_key: str | None = None,
) -> WeatherSummary | None:
    """Return a short human-readable summary of today's weather."""

    resolved = resolve_weather_provider(provider)
    result = fetch_forecast(
        resolved,
        latitude,
        longitude,
        timezone,
        weatherapi_api_key=weatherapi_api_key,
    )
    if result is None:
        return None
    text, temp_max, temp_min = result
    return WeatherSummary(text=text, temperature_max=temp_max, temperature_min=temp_min)

