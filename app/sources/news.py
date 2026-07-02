"""News ingestion: Google News geo feed + user RSS feeds, with tiered extraction.

Extraction order per article URL:
  1. Plain HTTP fetch + trafilatura.
  2. Zyte API (browser rendering + automatic article extraction) when configured.
  3. The RSS feed summary as a final fallback.
"""

from __future__ import annotations

import calendar
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin, urlparse

import feedparser
import httpx
import trafilatura

from ..credentials import Credentials
from ..episode_log import LogTimer, active_log
from ..http_retry import httpx_request_with_retry

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; MorningNewsBot/1.0; +https://github.com/morning-news)"
)
# Some sites (WAFs, Cloudflare rules) reject anything that isn't a browser.
# We identify honestly first and only fall back to this when blocked.
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_BLOCKED_STATUSES = frozenset({401, 403, 406, 451})
_MAX_FEED_WORKERS = 6
_MAX_EXTRACTION_WORKERS = 6
# Priority feeds only force-include stories published within this window;
# older entries (or ones without a date) compete like normal feed articles.
_PRIORITY_MAX_AGE_HOURS = 48
# A feed-embedded body at least this long is treated as the full article,
# so no web extraction is attempted for it.
_MIN_FEED_BODY_CHARS = 400
_extraction_semaphore = threading.Semaphore(_MAX_EXTRACTION_WORKERS)


@dataclass
class Article:
    title: str
    url: str
    publisher: str = ""
    summary: str = ""
    body: str = ""
    source_name: str = ""
    priority: bool = False
    published: datetime | None = None  # UTC, from the feed entry when available

    @property
    def content(self) -> str:
        """Best available text for the LLM (full body, else feed summary)."""

        return self.body.strip() or self.summary.strip()


@dataclass
class NewsSource:
    url: str
    name: str = ""
    is_google_news: bool = False
    # Priority feeds publish rarely; every fresh story they carry is selected.
    priority: bool = False


def build_google_news_url(locality: str, hl: str, gl: str, ceid: str) -> str | None:
    """Build a Google News location-headlines RSS URL from a locality name."""

    if not locality.strip():
        return None
    section = quote(locality.strip())
    return (
        f"https://news.google.com/rss/headlines/section/geo/{section}"
        f"?hl={hl}&gl={gl}&ceid={ceid}"
    )


def build_google_news_search_url(query: str, hl: str, gl: str, ceid: str) -> str:
    return (
        f"https://news.google.com/rss/search?q={quote(query)}"
        f"&hl={hl}&gl={gl}&ceid={ceid}"
    )


def build_local_news_sources(
    *,
    locality: str,
    admin1: str = "",
    country: str = "",
    hl: str,
    gl: str,
    ceid: str,
) -> list[NewsSource]:
    """Build Google News feeds for a location, with regional search fallbacks.

    Small towns often have no dedicated geo feed; broader search queries cover them.
    """

    sources: list[NewsSource] = []
    place = locality.strip()
    region = admin1.strip()
    country_name = country.strip()

    if place:
        geo_url = build_google_news_url(place, hl, gl, ceid)
        if geo_url:
            sources.append(
                NewsSource(url=geo_url, name=f"Local ({place})", is_google_news=True)
            )

    if region and region.lower() != place.lower():
        sources.append(
            NewsSource(
                url=build_google_news_search_url(f"{region} when:1d", hl, gl, ceid),
                name=f"Regional ({region})",
                is_google_news=True,
            )
        )

    if region and country_name:
        sources.append(
            NewsSource(
                url=build_google_news_search_url(
                    f"{region} {country_name} when:1d", hl, gl, ceid
                ),
                name=f"Regional ({region}, {country_name})",
                is_google_news=True,
            )
        )
    elif country_name and not region:
        sources.append(
            NewsSource(
                url=build_google_news_search_url(f"{country_name} when:1d", hl, gl, ceid),
                name=f"National ({country_name})",
                is_google_news=True,
            )
        )

    return sources


_INVALID_ARTICLE_TITLES = frozenset({"this feed is not available.", "(untitled)"})


def _is_valid_article(article: Article) -> bool:
    title = article.title.strip().lower()
    if not title or title in _INVALID_ARTICLE_TITLES:
        return False
    if "feed is not available" in title:
        return False
    return bool(article.url.strip())


def _is_google_news(url: str) -> bool:
    return "news.google.com" in urlparse(url).netloc


def _resolve_redirect(url: str) -> str:
    """Follow redirects to obtain the real publisher URL (Google News links)."""

    timer = LogTimer.start()
    try:
        with httpx.Client(
            follow_redirects=True, timeout=20, headers={"User-Agent": _USER_AGENT}
        ) as client:
            response = httpx_request_with_retry(lambda: client.get(url))
            final_url = str(response.url)
    except httpx.HTTPError as error:
        logger.info("Redirect resolution failed for %s: %s", url, error)
        audit = active_log()
        if audit is not None:
            audit.record(
                "news",
                "Resolve redirect",
                status="error",
                summary=url,
                request={"url": url},
                response={"error": str(error)},
                duration_ms=timer.elapsed_ms(),
            )
        return url
    resolved = url if _is_google_news(final_url) else final_url
    audit = active_log()
    if audit is not None:
        audit.record(
            "news",
            "Resolve redirect",
            summary=resolved if resolved != url else "Still on Google News",
            request={"url": url},
            response={"final_url": resolved},
            duration_ms=timer.elapsed_ms(),
        )
    return resolved


def _extract_with_trafilatura(url: str) -> str | None:
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
        return text or None
    except Exception as error:  # trafilatura can raise assorted parsing errors
        logger.info("trafilatura extraction failed for %s: %s", url, error)
        return None


def _extract_with_zyte(url: str, *, zyte_api_key: str | None) -> str | None:
    if not zyte_api_key:
        return None
    try:
        response = httpx_request_with_retry(
            lambda: httpx.post(
                "https://api.zyte.com/v1/extract",
                auth=(zyte_api_key, ""),
                json={"url": url, "article": True},
                timeout=60,
            )
        )
        response.raise_for_status()
        article = response.json().get("article") or {}
    except (httpx.HTTPError, ValueError) as error:
        logger.info("Zyte extraction failed for %s: %s", url, error)
        return None
    return (article.get("articleBody") or "").strip() or None


def extract_body(url: str, *, zyte_api_key: str | None = None) -> str:
    """Run the tiered extraction chain; returns '' if everything fails."""

    timer = LogTimer.start()
    text = _extract_with_trafilatura(url)
    method = "trafilatura" if text else None
    if not text:
        text = _extract_with_zyte(url, zyte_api_key=zyte_api_key)
        method = "zyte" if text else None

    audit = active_log()
    if audit is not None:
        audit.record(
            "news",
            "Extract article body",
            status="success" if text else "error",
            summary=f"{len(text)} chars via {method or 'none'}" if text else "Extraction failed",
            request={"url": url, "zyte_available": bool(zyte_api_key)},
            response={"method": method, "chars": len(text) if text else 0},
            duration_ms=timer.elapsed_ms(),
        )

    return text or ""


def _fetch_and_parse_feed(url: str):
    """Fetch a candidate feed URL with a bounded timeout and parse the body."""

    with httpx.Client(follow_redirects=True, timeout=15) as client:
        response = client.get(url, headers={"User-Agent": _USER_AGENT})
        if response.status_code in _BLOCKED_STATUSES:
            response = client.get(url, headers={"User-Agent": _BROWSER_USER_AGENT})
        response.raise_for_status()
    return feedparser.parse(response.content)


def discover_feed_url(page_url: str) -> str | None:
    """Find the RSS/Atom feed behind an HTML page URL.

    Users often paste a site's news page instead of its feed. Try HTML
    autodiscovery (<link rel="alternate">), then common conventions like
    WordPress's /feed/. Returns the first candidate that parses with entries.
    """

    html = ""
    base_url = page_url
    try:
        with httpx.Client(follow_redirects=True, timeout=20) as client:
            response = client.get(page_url, headers={"User-Agent": _USER_AGENT})
            if response.status_code in _BLOCKED_STATUSES:
                response = client.get(
                    page_url, headers={"User-Agent": _BROWSER_USER_AGENT}
                )
        html = response.text
        base_url = str(response.url)
    except httpx.HTTPError as error:
        logger.info("Feed discovery page fetch failed for %s: %s", page_url, error)

    candidates: list[str] = []
    for tag in re.findall(r"<link\b[^>]*>", html, flags=re.IGNORECASE):
        if not re.search(
            r"type=[\"']application/(?:rss|atom)\+xml[\"']", tag, flags=re.IGNORECASE
        ):
            continue
        href = re.search(r"href=[\"']([^\"']+)[\"']", tag)
        if href:
            candidates.append(urljoin(base_url, href.group(1)))

    split = urlparse(page_url)
    root = f"{split.scheme}://{split.netloc}"
    page = page_url.rstrip("/")
    for guess in (
        f"{page}/feed/",
        f"{root}/feed/",
        f"{root}/rss.xml",
        f"{root}/atom.xml",
        f"{root}/index.xml",
    ):
        if guess not in candidates:
            candidates.append(guess)

    # Prefer the feed most specific to the pasted page (e.g. a category feed
    # over the site-wide one, which usually appears first in the HTML head).
    candidates.sort(key=lambda candidate: 0 if candidate.startswith(page) else 1)

    for candidate in candidates:
        if candidate.rstrip("/") == page:
            continue
        if "/comments" in candidate:
            continue  # WordPress comment feeds are never what the user wants
        try:
            parsed = _fetch_and_parse_feed(candidate)
        except Exception:  # 404s, timeouts, parse errors — just try the next guess
            continue
        if parsed.entries:
            logger.info("Discovered feed %s behind page %s", candidate, page_url)
            return candidate
    return None


def resolve_feed_url(url: str) -> tuple[str, bool]:
    """Return (feed_url, is_valid_feed), discovering the real feed if needed."""

    try:
        parsed = _fetch_and_parse_feed(url)
    except Exception:
        parsed = None
    if parsed is not None and parsed.entries:
        return url, True
    discovered = discover_feed_url(url)
    if discovered:
        return discovered, True
    return url, False


def _parse_feed(source: NewsSource, max_entries: int) -> list[Article]:
    parsed = feedparser.parse(source.url, agent=_USER_AGENT)
    if not parsed.entries and getattr(parsed, "status", None) in _BLOCKED_STATUSES:
        # Site rejects our bot user-agent; retry as a browser.
        parsed = feedparser.parse(source.url, agent=_BROWSER_USER_AGENT)
    if parsed.bozo and not parsed.entries:
        logger.warning("Feed parse problem for %s: %s", source.url, parsed.get("bozo_exception"))
        if not source.is_google_news:
            # The stored URL may be an HTML page, not a feed (a common paste
            # mistake) — try to discover the real feed and use it for this run.
            discovered = discover_feed_url(source.url)
            if discovered:
                parsed = feedparser.parse(discovered, agent=_USER_AGENT)
                audit = active_log()
                if audit is not None:
                    audit.record(
                        "news",
                        "Discover feed URL",
                        summary=f"{source.name}: found feed at {discovered}",
                        request={"configured_url": source.url},
                        response={"feed_url": discovered, "entries": len(parsed.entries)},
                    )
    feed_title = getattr(parsed.feed, "title", source.name)

    articles: list[Article] = []
    for entry in parsed.entries[:max_entries]:
        link = getattr(entry, "link", "")
        if not link:
            continue
        publisher = feed_title
        entry_source = getattr(entry, "source", None)
        if entry_source is not None and getattr(entry_source, "title", None):
            publisher = entry_source.title
        articles.append(
            Article(
                title=getattr(entry, "title", "(untitled)"),
                url=link,
                publisher=publisher,
                summary=_clean_summary(getattr(entry, "summary", "")),
                body=_entry_body(entry),
                source_name=source.name,
                priority=source.priority,
                published=_entry_published(entry),
            )
        )
    return articles


def _entry_body(entry) -> str:
    """Full article text when the feed embeds it (WordPress content:encoded)."""

    for item in getattr(entry, "content", None) or []:
        text = _clean_summary(getattr(item, "value", ""))
        if text:
            return text
    return ""


def _entry_published(entry) -> datetime | None:
    """Best-effort UTC publish time from a feed entry."""

    for attribute in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attribute, None)
        if parsed:
            try:
                return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
            except (ValueError, OverflowError, TypeError):
                continue
    return None


def _clean_summary(summary: str) -> str:
    # feedparser sometimes returns HTML; strip tags crudely for the LLM.
    import re

    text = re.sub(r"<[^>]+>", " ", summary)
    return re.sub(r"\s+", " ", text).strip()


def _dedupe(articles: list[Article]) -> list[Article]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[Article] = []
    for article in articles:
        title_key = article.title.strip().lower()
        if article.url in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(article.url)
        seen_titles.add(title_key)
        unique.append(article)
    return unique


def _collect_from_source(source: NewsSource, max_entries_per_feed: int) -> list[Article]:
    timer = LogTimer.start()
    try:
        parsed = _parse_feed(source, max_entries_per_feed)
        valid = [article for article in parsed if _is_valid_article(article)]
        logger.info("Feed %r returned %d articles", source.name, len(valid))
        audit = active_log()
        if audit is not None:
            audit.record(
                "news",
                "Fetch RSS feed",
                summary=f"{source.name}: {len(valid)} article(s)",
                request={"name": source.name, "url": source.url},
                response={
                    "articles": [
                        {"title": article.title, "url": article.url, "publisher": article.publisher}
                        for article in valid
                    ]
                },
                duration_ms=timer.elapsed_ms(),
            )
        return valid
    except Exception as error:
        audit = active_log()
        if audit is not None:
            audit.record(
                "news",
                "Fetch RSS feed",
                status="error",
                summary=f"{source.name}: failed",
                request={"name": source.name, "url": source.url},
                response={"error": str(error)},
                duration_ms=timer.elapsed_ms(),
            )
        logger.warning("Failed to read feed %s: %s", source.url, error)
        return []


def _collect_from_sources(
    sources: list[NewsSource],
    max_entries_per_feed: int,
) -> list[Article]:
    if not sources:
        return []

    collected: list[Article] = []
    max_workers = min(len(sources), _MAX_FEED_WORKERS)
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="news-feed") as executor:
        feed_results = executor.map(
            lambda source: copy_context().run(_collect_from_source, source, max_entries_per_feed),
            sources,
        )
        for articles in feed_results:
            collected.extend(articles)
    return collected


def gather_articles(
    sources: list[NewsSource],
    max_entries_per_feed: int = 15,
    max_articles: int = 25,
    extract: bool = True,
    *,
    zyte_api_key: str | None = None,
    exclude_urls: set[str] | None = None,
    exclude_titles: set[str] | None = None,
) -> list[Article]:
    """Collect, dedupe, and (optionally) extract bodies for candidate articles.

    User-supplied RSS feeds are prioritized so they are not crowded out by
    Google News regional feeds hitting the article cap; fresh stories from
    priority feeds (published within the last 48 hours) are selected in full,
    ahead of everything else. Articles matching
    `exclude_urls`/`exclude_titles` (stories aired in past episodes) are
    dropped so a story is never repeated across episodes.
    """

    exclude_urls = exclude_urls or set()
    exclude_titles = exclude_titles or set()

    def is_repeat(article: Article) -> bool:
        return (
            article.url in exclude_urls
            or article.title.strip().lower() in exclude_titles
        )

    user_sources = [source for source in sources if not source.is_google_news]
    auto_sources = [source for source in sources if source.is_google_news]

    user_articles = _dedupe(_collect_from_sources(user_sources, max_entries_per_feed))
    auto_articles = _dedupe(_collect_from_sources(auto_sources, max_entries_per_feed))

    repeats_skipped = sum(is_repeat(a) for a in user_articles + auto_articles)
    user_articles = [article for article in user_articles if not is_repeat(article)]
    auto_articles = [article for article in auto_articles if not is_repeat(article)]

    # Only force-include priority stories that are actually fresh; older or
    # undated entries from priority feeds compete like normal feed articles.
    freshness_cutoff = datetime.now(timezone.utc) - timedelta(hours=_PRIORITY_MAX_AGE_HOURS)

    def force_include(article: Article) -> bool:
        return (
            article.priority
            and article.published is not None
            and article.published >= freshness_cutoff
        )

    priority_articles = [article for article in user_articles if force_include(article)]
    user_articles = [article for article in user_articles if not force_include(article)]
    for article in user_articles:
        article.priority = False  # stale — drop the must-include tag for the LLM

    selected: list[Article] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()

    def take(candidates: list[Article], limit: int) -> None:
        for article in candidates:
            if len(selected) >= limit:
                break
            title_key = article.title.strip().lower()
            if article.url in seen_urls or title_key in seen_titles:
                continue
            selected.append(article)
            seen_urls.add(article.url)
            seen_titles.add(title_key)

    # Priority feeds publish rarely — take every fresh story, even past the cap.
    take(priority_articles, max(max_articles, len(priority_articles)))
    user_quota = max(8, max_articles // 2)
    take(user_articles, min(max_articles, len(selected) + user_quota))
    take(auto_articles, max_articles)
    take(user_articles, max_articles)

    if repeats_skipped:
        logger.info("Skipped %d article(s) already aired in past episodes", repeats_skipped)
        audit = active_log()
        if audit is not None:
            audit.record(
                "news",
                "Skip repeated stories",
                summary=f"{repeats_skipped} article(s) already aired in past episodes",
                response={"skipped": repeats_skipped},
            )

    logger.info(
        "Selected %d articles (%d from user feeds, %d from Google News)",
        len(selected),
        sum(1 for article in selected if article.source_name),
        sum(1 for article in selected if _is_google_news(article.url)),
    )

    if extract:
        def extract_article(article: Article) -> None:
            if len(article.body) >= _MIN_FEED_BODY_CHARS:
                return  # the feed already carried the full text
            with _extraction_semaphore:
                target_url = article.url
                if _is_google_news(target_url):
                    target_url = _resolve_redirect(target_url)
                    article.url = target_url
                if not _is_google_news(target_url):
                    article.body = extract_body(target_url, zyte_api_key=zyte_api_key)

        max_workers = min(len(selected), _MAX_EXTRACTION_WORKERS)
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="news-extract") as executor:
            list(
                executor.map(
                    lambda article: copy_context().run(extract_article, article),
                    selected,
                )
            )
        if exclude_urls:
            # Google News links only reveal the real publisher URL after redirect
            # resolution, so re-check for already-aired stories here.
            resolved_repeats = [a for a in selected if a.url in exclude_urls]
            if resolved_repeats:
                logger.info(
                    "Dropped %d article(s) whose resolved URL already aired",
                    len(resolved_repeats),
                )
                selected = [a for a in selected if a.url not in exclude_urls]
    return selected
