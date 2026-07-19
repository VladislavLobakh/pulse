"""Newsletter collector — configured RSS/Atom feeds with deterministic keyword relevance."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from html import unescape
from urllib.parse import urlsplit, urlunsplit

import feedparser
import httpx

from pulse.logging_config import get_logger
from pulse.models import Source, SourceItem, SourceItemList
from pulse.patterns.parallel import normalize_url

logger = get_logger(__name__)

FEED_TIMEOUT_SECONDS = 10.0
MAX_RESULTS = 10
SUMMARY_MAX_CHARS = 1000

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "in", "is", "it", "of", "on", "or", "that", "the", "to", "with",
    }
)  # fmt: skip
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class NewsletterFeed:
    name: str
    url: str


NEWSLETTER_FEEDS: tuple[NewsletterFeed, ...] = (
    NewsletterFeed(name="Latent Space", url="https://www.latent.space/feed"),
    NewsletterFeed(name="Simon Willison", url="https://simonwillison.net/atom/everything/"),
)


class NewsletterFeedError(RuntimeError):
    """A feed response was not usable, or every configured feed failed."""


@dataclass
class NewsletterFetchResult:
    items: SourceItemList
    failed_feeds: tuple[str, ...]


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _query_tokens(query: str) -> list[str]:
    tokens = [token for token in dict.fromkeys(_tokenize(query)) if token not in _STOPWORDS]
    if not tokens:
        raise ValueError("newsletter query has no scoreable terms")
    return tokens


def _matches(token: str, haystack: set[str]) -> bool:
    if token in haystack:
        return True
    # Prefix matching absorbs plurals/suffixes; short tokens stay exact to avoid over-matching.
    return len(token) >= 4 and any(word.startswith(token) for word in haystack)


def _score(query_tokens: list[str], text: str) -> float:
    haystack = set(_tokenize(text))
    matched = sum(1 for token in query_tokens if _matches(token, haystack))
    return matched / len(query_tokens)


def relevance_score(query: str, text: str) -> float:
    """Fraction of non-stopword query tokens found in the text, in [0, 1]."""
    return _score(_query_tokens(query), text)


def _clean_text(raw: str) -> str:
    return " ".join(_HTML_TAG_RE.sub(" ", unescape(raw)).split())


def _entry_text(entry: feedparser.FeedParserDict) -> str:
    for content in entry.get("content") or []:
        value = (content.get("value") or "").strip()
        if value:
            return value
    return entry.get("summary") or ""


def _entry_url(entry: feedparser.FeedParserDict) -> str | None:
    link = (entry.get("link") or "").strip()
    try:
        parts = urlsplit(link)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _published_date(entry: feedparser.FeedParserDict) -> str:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return date(*parsed[:3]).isoformat()
    return ""


def _normalize_entry(
    feed: NewsletterFeed,
    entry: feedparser.FeedParserDict,
    query_tokens: list[str],
) -> SourceItem | None:
    title = " ".join((entry.get("title") or "").split())
    url = _entry_url(entry)
    if not title or not url:
        return None
    full_text = _clean_text(_entry_text(entry))
    return SourceItem(
        title=title,
        url=url,
        score=_score(query_tokens, f"{title} {full_text}"),
        summary=f"[{feed.name}] {full_text}"[:SUMMARY_MAX_CHARS].rstrip(),
        source=Source.NEWSLETTER,
        published_date=_published_date(entry),
    )


def _parse_feed(feed: NewsletterFeed, data: bytes, query_tokens: list[str]) -> SourceItemList:
    parsed = feedparser.parse(data)
    if not parsed.entries and (parsed.bozo or not parsed.version):
        raise NewsletterFeedError("response is not a usable feed")
    if parsed.bozo:
        logger.warning(
            "Newsletter feed %s parsed with warnings: %s",
            feed.name,
            type(parsed.bozo_exception).__name__,
        )

    items: SourceItemList = []
    for entry in parsed.entries:
        try:
            item = _normalize_entry(feed, entry, query_tokens)
        except Exception as exc:
            logger.warning("Newsletter entry in %s skipped: %s", feed.name, type(exc).__name__)
            continue
        if item is not None:
            items.append(item)
    return items


def _validate_max_results(max_results: int) -> None:
    if isinstance(max_results, bool) or not isinstance(max_results, int):
        raise ValueError("max_results must be an integer")
    if not 1 <= max_results <= MAX_RESULTS:
        raise ValueError(f"max_results must be between 1 and {MAX_RESULTS}")


def _fetch_feed(feed: NewsletterFeed) -> bytes:
    response = httpx.get(
        feed.url,
        headers={"User-Agent": "PULSE/0.1"},
        follow_redirects=True,
        timeout=FEED_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.content


def _dedup(items: SourceItemList) -> SourceItemList:
    seen: set[str] = set()
    unique: SourceItemList = []
    for item in items:
        key = normalize_url(item.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def fetch_newsletter_items(
    query: str,
    *,
    max_results: int = MAX_RESULTS,
    feeds: Sequence[NewsletterFeed] = NEWSLETTER_FEEDS,
) -> NewsletterFetchResult:
    """Fetch configured feeds, keep query-relevant entries, and report failed feeds."""
    _validate_max_results(max_results)
    query_tokens = _query_tokens(query)

    collected: SourceItemList = []
    failed: list[str] = []
    for feed in feeds:
        try:
            collected.extend(_parse_feed(feed, _fetch_feed(feed), query_tokens))
        except Exception as exc:
            logger.warning("Newsletter feed %s failed: %s", feed.name, type(exc).__name__)
            failed.append(feed.name)
    if feeds and len(failed) == len(feeds):
        raise NewsletterFeedError("all newsletter feeds failed")

    relevant = _dedup([item for item in collected if item.score > 0.0])
    # Stable sort: equal scores keep (feed-config, entry) order, so output is deterministic.
    relevant.sort(key=lambda item: -item.score)
    return NewsletterFetchResult(items=relevant[:max_results], failed_feeds=tuple(failed))
