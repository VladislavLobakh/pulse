"""YouTube collector — Tavily discovery, URL normalization, transcript excerpts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

import requests
from youtube_transcript_api import (
    AgeRestricted,
    NoTranscriptFound,
    PoTokenRequired,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeTranscriptApi,
)

from pulse.collectors.tavily import search_articles
from pulse.logging_config import get_logger
from pulse.models import Source, SourceItem, SourceItemList

logger = get_logger(__name__)

YOUTUBE_DOMAINS = ["youtube.com"]
MAX_RESULTS = 10
MAX_TRANSCRIPTS = 5
TRANSCRIPT_EXCERPT_MAX_CHARS = 1500
TRANSCRIPT_LANGUAGES = ("en",)
TRANSCRIPT_TIMEOUT_SECONDS = 20.0

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Per-video caption problems skip only that video; every other failure
# (request blocks, unparsable data, unknown subclasses) must propagate.
_ITEM_SKIP_EXCEPTIONS = (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
    VideoUnplayable,
    AgeRestricted,
    PoTokenRequired,
)


class _TimeoutSession(requests.Session):
    def request(self, method, url, **kwargs):
        # setdefault would let an explicit timeout=None ("wait forever") through.
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = TRANSCRIPT_TIMEOUT_SECONDS
        return super().request(method, url, **kwargs)


@dataclass
class SkippedVideo:
    video_id: str
    reason: str


@dataclass
class YouTubeCollectResult:
    items: SourceItemList = field(default_factory=list)
    skipped: list[SkippedVideo] = field(default_factory=list)


def _is_youtube_host(host: str | None) -> bool:
    return host in {"youtube.com", "www.youtube.com", "m.youtube.com"}


def video_id_from_url(url: str) -> str | None:
    """Resolve any supported YouTube video URL variant to its canonical id."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"}:
        return None

    host = parts.hostname
    segments = [segment for segment in parts.path.split("/") if segment]
    candidate: str | None = None
    if _is_youtube_host(host):
        if segments == ["watch"]:
            candidate = next(iter(parse_qs(parts.query).get("v", [])), None)
        elif len(segments) == 2 and segments[0] in {"shorts", "embed"}:
            candidate = segments[1]
    elif host == "youtu.be" and len(segments) == 1:
        candidate = segments[0]
    elif host == "www.youtube-nocookie.com" and len(segments) == 2 and segments[0] == "embed":
        candidate = segments[1]

    if candidate and _VIDEO_ID_RE.fullmatch(candidate):
        return candidate
    return None


def canonical_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _validate_limit(value: int, name: str, upper_bound: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not 1 <= value <= upper_bound:
        raise ValueError(f"{name} must be between 1 and {upper_bound}")


def _transcript_excerpt(fetched) -> str:
    text = " ".join(snippet.text for snippet in fetched.snippets)
    return " ".join(text.split())[:TRANSCRIPT_EXCERPT_MAX_CHARS].rstrip()


def _candidate_videos(discovered: SourceItemList) -> list[tuple[str, SourceItem]]:
    candidates: list[tuple[str, SourceItem]] = []
    seen: set[str] = set()
    for item in discovered:
        video_id = video_id_from_url(item.url)
        if video_id is None or video_id in seen:
            continue
        seen.add(video_id)
        candidates.append((video_id, item))
    return candidates


def search_youtube_videos(
    query: str,
    *,
    max_results: int = MAX_RESULTS,
    max_transcripts: int = MAX_TRANSCRIPTS,
) -> YouTubeCollectResult:
    """Discover videos once, then turn available transcripts into bounded items."""
    _validate_limit(max_results, "max_results", MAX_RESULTS)
    _validate_limit(max_transcripts, "max_transcripts", MAX_TRANSCRIPTS)

    discovered = search_articles(
        query,
        Source.YOUTUBE,
        max_results=max_results,
        include_domains=YOUTUBE_DOMAINS,
    )
    candidates = _candidate_videos(discovered)[:max_transcripts]

    result = YouTubeCollectResult()
    with _TimeoutSession() as session:
        api = YouTubeTranscriptApi(http_client=session)
        for video_id, discovered_item in candidates:
            try:
                fetched = api.fetch(video_id, languages=TRANSCRIPT_LANGUAGES)
            except _ITEM_SKIP_EXCEPTIONS as exc:
                reason = type(exc).__name__
                logger.warning("YouTube transcript skipped video=%s reason=%s", video_id, reason)
                result.skipped.append(SkippedVideo(video_id=video_id, reason=reason))
                continue

            excerpt = _transcript_excerpt(fetched)
            if not excerpt:
                logger.warning(
                    "YouTube transcript skipped video=%s reason=%s", video_id, "empty_transcript"
                )
                result.skipped.append(SkippedVideo(video_id=video_id, reason="empty_transcript"))
                continue

            result.items.append(
                SourceItem(
                    title=discovered_item.title,
                    url=canonical_watch_url(video_id),
                    score=discovered_item.score,
                    summary=excerpt,
                    source=Source.YOUTUBE,
                    published_date=discovered_item.published_date,
                )
            )
    return result
