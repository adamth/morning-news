"""Stock watchlist quotes via Finnhub (recommended) with Yahoo Finance fallback."""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from ..credentials import Credentials

logger = logging.getLogger(__name__)

FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_CRUMB_URL = "https://query2.finance.yahoo.com/v1/test/getcrumb"
YAHOO_WARMUP_URL = "https://finance.yahoo.com/quote/AAPL/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
FLAT_THRESHOLD = 0.05  # percent — treat smaller moves as flat
HTTP_TIMEOUT = 20.0

_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9.^\-]{1,12}$")

# Finnhub quotes US symbols; map common indices to liquid ETF proxies.
_FINNHUB_SYMBOL_ALIASES: dict[str, str] = {
    "^GSPC": "SPY",
    "^IXIC": "QQQ",
    "^DJI": "DIA",
    "^RUT": "IWM",
    "^FTSE": "VUKE.L",
    "^N225": "1321.T",
}

_REACTIONS: dict[str, dict[str, list[str]]] = {
    "bullish": {
        "mild": [
            "Not a bad morning to peek at the portfolio over toast.",
            "Green across the board — someone's portfolio is feeling smug today.",
            "The watchlist woke up on the right side of the bed.",
        ],
        "mature": [
            "Everything's up — finally, a morning where nobody got screwed.",
            "Green day. Maybe the market and you can both be insufferable at breakfast.",
            "Solid gains — almost enough to pretend you knew what you were doing all along.",
        ],
    },
    "bearish": {
        "mild": [
            "Might want to skip opening the brokerage app until after coffee.",
            "Red morning — the market chose violence before you chose cereal.",
            "Down day. The numbers are not in a cooperative mood.",
        ],
        "mature": [
            "Rough session — the market absolutely fucked your watchlist overnight.",
            "Everything's bleeding. Pour something stronger than coffee.",
            "Red across the board. Consider this your daily reminder that stonks go down too.",
        ],
    },
    "mixed": {
        "mild": [
            "Half up, half down — the market couldn't make up its mind.",
            "Mixed bag today — like a household where nobody agrees on the thermostat.",
            "Some winners, some losers — a very democratic morning for your holdings.",
        ],
        "mature": [
            "Split decision — half your stocks are heroes, half got absolutely wrecked.",
            "Mixed results. The market's playing favorites and you're not all in the good books.",
            "Winners and losers — like a family argument, but with money and no resolution.",
        ],
    },
    "flat": {
        "mild": [
            "Barely moved — the financial equivalent of waiting for water to boil.",
            "Flat day. Your watchlist is napping.",
            "Not much happening — the market is having a lie-in too.",
        ],
        "mature": [
            "Dead flat. Even your stocks can't be bothered today.",
            "Nothing moved. The market is as exciting as leftover toast.",
            "Flatline morning — your portfolio and your motivation are in sync.",
        ],
    },
}


@dataclass
class QuoteSnapshot:
    symbol: str
    change_percent: float


@dataclass
class MarketSummary:
    text: str
    reaction_hint: str


def normalize_symbol(raw: str) -> str | None:
    """Return an uppercase ticker or None if invalid."""

    symbol = raw.strip().upper()
    if not symbol or not _SYMBOL_PATTERN.match(symbol):
        return None
    return symbol


def get_market_summary(
    symbols: list[str],
    *,
    credentials: Credentials,
    mature_reactions: bool = False,
) -> MarketSummary | None:
    """Fetch 24-hour change for each symbol and return an aggregate briefing."""

    unique_symbols = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = normalize_symbol(raw)
        if symbol and symbol not in seen:
            seen.add(symbol)
            unique_symbols.append(symbol)

    if not unique_symbols:
        return None

    snapshots = _fetch_quotes(unique_symbols, credentials=credentials)
    if not snapshots:
        if not credentials.finnhub_api_key:
            logger.warning(
                "Stock quotes unavailable — add a Finnhub API key in Settings → Connections "
                "(free at https://finnhub.io). Yahoo Finance fallback is often rate-limited."
            )
        return None

    return _build_summary(snapshots, mature_reactions=mature_reactions)


def _fetch_quotes(symbols: list[str], *, credentials: Credentials) -> list[QuoteSnapshot]:
    snapshots: list[QuoteSnapshot] = []
    yahoo_client: httpx.Client | None = None
    yahoo_crumb: str | None = None

    if not credentials.finnhub_api_key:
        yahoo_client, yahoo_crumb = _open_yahoo_session()

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    with httpx.Client(headers=headers, follow_redirects=True, timeout=HTTP_TIMEOUT) as client:
        for symbol in symbols:
            snapshot = None
            if credentials.finnhub_api_key:
                snapshot = _fetch_finnhub_quote(client, symbol, credentials.finnhub_api_key)
            if snapshot is None and yahoo_client is not None:
                snapshot = _fetch_yahoo_quote(yahoo_client, symbol, yahoo_crumb)
            if snapshot is not None:
                snapshots.append(snapshot)

    if yahoo_client is not None:
        yahoo_client.close()

    return snapshots


def _fetch_finnhub_quote(
    client: httpx.Client,
    symbol: str,
    api_key: str,
) -> QuoteSnapshot | None:
    if not api_key:
        return None

    lookup_symbols = [symbol]
    alias = _FINNHUB_SYMBOL_ALIASES.get(symbol)
    if alias and alias not in lookup_symbols:
        lookup_symbols.append(alias)

    for lookup_symbol in lookup_symbols:
        try:
            response = client.get(
                FINNHUB_QUOTE_URL,
                params={"symbol": lookup_symbol, "token": api_key},
            )
            response.raise_for_status()
            payload = response.json()
            change_percent = payload.get("dp")
            current_price = payload.get("c")
            if change_percent is None or current_price in (None, 0):
                continue
            return QuoteSnapshot(symbol=symbol, change_percent=float(change_percent))
        except (httpx.HTTPError, ValueError, TypeError) as error:
            logger.warning("Finnhub quote lookup failed for %s: %s", lookup_symbol, error)

    return None


def _open_yahoo_session() -> tuple[httpx.Client | None, str | None]:
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    client = httpx.Client(headers=headers, follow_redirects=True, timeout=HTTP_TIMEOUT)
    try:
        warmup = client.get(YAHOO_WARMUP_URL)
        warmup.raise_for_status()
        crumb_response = client.get(YAHOO_CRUMB_URL)
        if crumb_response.status_code == 429:
            logger.info("Yahoo Finance rate-limited — use FINNHUB_API_KEY for reliable stock quotes")
            client.close()
            return None, None
        crumb_response.raise_for_status()
        crumb = crumb_response.text.strip()
        return client, crumb or None
    except httpx.HTTPError as error:
        logger.warning("Yahoo Finance session failed: %s", error)
        client.close()
        return None, None


def _fetch_yahoo_quote(
    client: httpx.Client,
    symbol: str,
    crumb: str | None,
) -> QuoteSnapshot | None:
    encoded_symbol = quote(symbol, safe="")
    params = {"range": "5d", "interval": "1d"}
    if crumb:
        params["crumb"] = crumb

    try:
        response = client.get(YAHOO_CHART_URL.format(symbol=encoded_symbol), params=params)
        if response.status_code == 429:
            return None
        response.raise_for_status()
        payload = response.json()
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            return None
        meta = result[0].get("meta") or {}
        change_percent = _change_percent_from_yahoo(meta, result[0])
        if change_percent is None:
            return None
        return QuoteSnapshot(symbol=symbol, change_percent=change_percent)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as error:
        logger.warning("Yahoo quote lookup failed for %s: %s", symbol, error)
        return None


def _change_percent_from_yahoo(meta: dict, result: dict) -> float | None:
    price = meta.get("regularMarketPrice")
    previous_close = meta.get("chartPreviousClose") or meta.get("previousClose")

    if price is not None and previous_close:
        return (float(price) - float(previous_close)) / float(previous_close) * 100

    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    valid_closes = [value for value in closes if value is not None]
    if len(valid_closes) >= 2:
        previous, current = valid_closes[-2], valid_closes[-1]
        if previous:
            return (current - previous) / previous * 100
    return None


def _build_summary(
    snapshots: list[QuoteSnapshot],
    *,
    mature_reactions: bool,
) -> MarketSummary:
    total = len(snapshots)
    up_count = sum(1 for item in snapshots if item.change_percent > FLAT_THRESHOLD)
    down_count = sum(1 for item in snapshots if item.change_percent < -FLAT_THRESHOLD)
    flat_count = total - up_count - down_count
    average_change = sum(item.change_percent for item in snapshots) / total

    direction = _overall_direction(up_count, down_count, flat_count, average_change)
    text = _format_aggregate_text(
        total=total,
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        average_change=average_change,
        direction=direction,
    )
    reaction_hint = _pick_reaction(direction, mature_reactions=mature_reactions)
    return MarketSummary(text=text, reaction_hint=reaction_hint)


def _overall_direction(
    up_count: int,
    down_count: int,
    flat_count: int,
    average_change: float,
) -> str:
    total = up_count + down_count + flat_count
    if up_count == total:
        return "bullish"
    if down_count == total:
        return "bearish"
    if flat_count == total:
        return "flat"
    if up_count > down_count and average_change > FLAT_THRESHOLD:
        return "bullish"
    if down_count > up_count and average_change < -FLAT_THRESHOLD:
        return "bearish"
    if abs(average_change) <= FLAT_THRESHOLD and up_count == down_count:
        return "flat"
    return "mixed"


def _format_aggregate_text(
    *,
    total: int,
    up_count: int,
    down_count: int,
    flat_count: int,
    average_change: float,
    direction: str,
) -> str:
    parts: list[str] = []

    if direction == "bullish":
        parts.append(f"Mostly up — {up_count} of {total} holdings gained over the last day")
    elif direction == "bearish":
        parts.append(f"Mostly down — {down_count} of {total} holdings fell over the last day")
    elif direction == "flat":
        parts.append(f"Flat overall — {flat_count} of {total} holdings barely moved")
    else:
        mixed = f"Mixed — {up_count} up, {down_count} down"
        if flat_count:
            mixed += f", {flat_count} flat"
        parts.append(f"{mixed} across {total} holdings")

    average_label = "up" if average_change > 0 else "down" if average_change < 0 else "flat"
    parts.append(
        f"averaging about {abs(average_change):.1f}% {average_label} overall"
    )
    return ", ".join(parts) + "."


def _pick_reaction(direction: str, *, mature_reactions: bool) -> str:
    tone = "mature" if mature_reactions else "mild"
    pool = _REACTIONS.get(direction, _REACTIONS["mixed"])[tone]
    return random.choice(pool)
