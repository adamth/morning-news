"""News ingestion: Google News geo feed + user RSS feeds, with tiered extraction.

Extraction order per article URL:
  1. Plain HTTP fetch + trafilatura.
  2. Zyte API (browser rendering + automatic article extraction) when configured.
  3. The RSS feed summary as a final fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import quote, urlparse

import feedparser
import httpx
import trafilatura

from ..config import config

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; MorningNewsBot/1.0; +https://github.com/morning-news)"
)


@dataclass
class Article:
    title: str
    url: str
    publisher: str = ""
    summary: str = ""
    body: str = ""
    source_name: str = ""

    @property
    def content(self) -> str:
        """Best available text for the LLM (full body, else feed summary)."""

        return self.body.strip() or self.summary.strip()


@dataclass
class NewsSource:
    url: str
    name: str = ""
    is_google_news: bool = False


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

    try:
        with httpx.Client(
            follow_redirects=True, timeout=20, headers={"User-Agent": _USER_AGENT}
        ) as client:
            response = client.get(url)
            final_url = str(response.url)
    except httpx.HTTPError as error:
        logger.info("Redirect resolution failed for %s: %s", url, error)
        return url
    if _is_google_news(final_url):
        return url
    return final_url


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


def _extract_with_zyte(url: str) -> str | None:
    if not config.zyte_api_key:
        return None
    try:
        response = httpx.post(
            "https://api.zyte.com/v1/extract",
            auth=(config.zyte_api_key, ""),
            json={"url": url, "article": True},
            timeout=60,
        )
        response.raise_for_status()
        article = response.json().get("article") or {}
    except (httpx.HTTPError, ValueError) as error:
        logger.info("Zyte extraction failed for %s: %s", url, error)
        return None
    return (article.get("articleBody") or "").strip() or None


def extract_body(url: str) -> str:
    """Run the tiered extraction chain; returns '' if everything fails."""

    text = _extract_with_trafilatura(url)
    if text:
        return text
    text = _extract_with_zyte(url)
    if text:
        return text
    return ""


def _parse_feed(source: NewsSource, max_entries: int) -> list[Article]:
    parsed = feedparser.parse(source.url, agent=_USER_AGENT)
    if parsed.bozo and not parsed.entries:
        logger.warning("Feed parse problem for %s: %s", source.url, parsed.get("bozo_exception"))
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
                source_name=source.name,
            )
        )
    return articles


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


def _collect_from_sources(
    sources: list[NewsSource],
    max_entries_per_feed: int,
) -> list[Article]:
    collected: list[Article] = []
    for source in sources:
        try:
            parsed = _parse_feed(source, max_entries_per_feed)
            valid = [article for article in parsed if _is_valid_article(article)]
            logger.info("Feed %r returned %d articles", source.name, len(valid))
            collected.extend(valid)
        except Exception as error:
            logger.warning("Failed to read feed %s: %s", source.url, error)
    return collected


def gather_articles(
    sources: list[NewsSource],
    max_entries_per_feed: int = 15,
    max_articles: int = 25,
    extract: bool = True,
) -> list[Article]:
    """Collect, dedupe, and (optionally) extract bodies for candidate articles.

    User-supplied RSS feeds are prioritized so they are not crowded out by
    Google News regional feeds hitting the article cap.
    """

    user_sources = [source for source in sources if not source.is_google_news]
    auto_sources = [source for source in sources if source.is_google_news]

    user_articles = _dedupe(_collect_from_sources(user_sources, max_entries_per_feed))
    auto_articles = _dedupe(_collect_from_sources(auto_sources, max_entries_per_feed))

    user_quota = (
        min(len(user_articles), max(8, max_articles // 2))
        if user_articles
        else 0
    )
    selected = user_articles[:user_quota]
    seen_urls = {article.url for article in selected}
    seen_titles = {article.title.strip().lower() for article in selected}

    for article in auto_articles:
        if len(selected) >= max_articles:
            break
        title_key = article.title.strip().lower()
        if article.url in seen_urls or title_key in seen_titles:
            continue
        selected.append(article)
        seen_urls.add(article.url)
        seen_titles.add(title_key)

    for article in user_articles[user_quota:]:
        if len(selected) >= max_articles:
            break
        title_key = article.title.strip().lower()
        if article.url in seen_urls or title_key in seen_titles:
            continue
        selected.append(article)
        seen_urls.add(article.url)
        seen_titles.add(title_key)

    logger.info(
        "Selected %d articles (%d from user feeds, %d from Google News)",
        len(selected),
        sum(1 for article in selected if article.source_name),
        sum(1 for article in selected if _is_google_news(article.url)),
    )

    if extract:
        for article in selected:
            target_url = article.url
            if _is_google_news(target_url):
                target_url = _resolve_redirect(target_url)
                article.url = target_url
            if not _is_google_news(target_url):
                article.body = extract_body(target_url)
    return selected
