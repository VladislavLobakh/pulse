"""Tests for the YouTube collector — all discovery and transcript calls are mocked."""

from __future__ import annotations

import pytest
import requests
from youtube_transcript_api import (
    AgeRestricted,
    CouldNotRetrieveTranscript,
    IpBlocked,
    NoTranscriptFound,
    PoTokenRequired,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeRequestFailed,
)

import pulse.collectors.youtube as youtube
from pulse.models import Source, SourceItem

VIDEO_ID = "dQw4w9WgXcQ"
OTHER_ID = "abcdefghijk"
THIRD_ID = "AAAAAAAAAA1"
FOURTH_ID = "zzzzzzzzzz2"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch) -> None:
    monkeypatch.setattr(
        youtube,
        "search_articles",
        lambda *args, **kwargs: pytest.fail("Tavily search must not be called"),
    )
    monkeypatch.setattr(
        youtube,
        "YouTubeTranscriptApi",
        lambda *args, **kwargs: pytest.fail("transcript API must not be constructed"),
    )


def _discovery_item(
    url: str,
    *,
    title: str = "An AI talk",
    score: float = 0.8,
    published_date: str = "2026-01-05",
) -> SourceItem:
    return SourceItem(
        title=title,
        url=url,
        score=score,
        summary="A search snippet.",
        source=Source.YOUTUBE,
        published_date=published_date,
    )


class _Snippet:
    def __init__(self, text: str) -> None:
        self.text = text


class _Fetched:
    def __init__(self, texts: list[str]) -> None:
        self.snippets = [_Snippet(text) for text in texts]


def _install_discovery(monkeypatch, items: list[SourceItem]) -> list[dict]:
    calls: list[dict] = []

    def fake_search(query, source, **kwargs):
        calls.append({"query": query, "source": source, **kwargs})
        return items

    monkeypatch.setattr(youtube, "search_articles", fake_search)
    return calls


def _install_api(monkeypatch, transcripts: dict[str, list[str] | Exception]) -> dict:
    record: dict = {"clients": [], "fetches": []}

    class FakeApi:
        def __init__(self, http_client=None) -> None:
            record["clients"].append(http_client)

        def fetch(self, video_id, languages=None):
            record["fetches"].append({"video_id": video_id, "languages": languages})
            outcome = transcripts[video_id]
            if isinstance(outcome, Exception):
                raise outcome
            return _Fetched(outcome)

    monkeypatch.setattr(youtube, "YouTubeTranscriptApi", FakeApi)
    return record


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"http://youtube.com/watch?v={VIDEO_ID}",
        f"https://www.youtube.com/watch?v={VIDEO_ID}&t=42s&list=PL123&index=2",
        f"https://m.youtube.com/watch?v={VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}",
        f"https://youtu.be/{VIDEO_ID}?si=abc123",
        f"https://www.youtube.com/shorts/{VIDEO_ID}",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        f"https://www.youtube-nocookie.com/embed/{VIDEO_ID}",
        f"  https://www.youtube.com/watch?v={VIDEO_ID}  ",
    ],
)
def test_video_id_from_url_accepts_supported_variants(url: str) -> None:
    assert youtube.video_id_from_url(url) == VIDEO_ID


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/channel/UC12345",
        "https://www.youtube.com/@somehandle",
        "https://www.youtube.com/c/somechannel",
        "https://www.youtube.com/user/someuser",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/results?search_query=ai",
        "https://www.youtube.com/feed/subscriptions",
        "https://www.youtube.com/",
        "https://www.youtube.com/watch",
        "https://www.youtube.com/watch?v=short",
        f"https://www.youtube.com/watch?v={VIDEO_ID}1",
        "https://www.youtube.com/watch?v=dQw4w9WgXc*",
        f"https://music.youtube.com/watch?v={VIDEO_ID}",
        f"https://youtube.com.evil.com/watch?v={VIDEO_ID}",
        f"https://evil.com/watch?v={VIDEO_ID}",
        f"ftp://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://www.youtube-nocookie.com/watch?v={VIDEO_ID}",
        "https://youtu.be/",
        "https://[",
        "",
    ],
)
def test_video_id_from_url_rejects_non_video_urls(url: str) -> None:
    assert youtube.video_id_from_url(url) is None


def test_search_normalizes_discovered_video_into_source_item(monkeypatch) -> None:
    discovered = _discovery_item(f"https://youtu.be/{VIDEO_ID}?si=share")
    search_calls = _install_discovery(monkeypatch, [discovered])
    _install_api(monkeypatch, {VIDEO_ID: ["Hello", "world"]})

    result = youtube.search_youtube_videos("agentic ai", max_results=3)

    assert search_calls == [
        {
            "query": "agentic ai",
            "source": Source.YOUTUBE,
            "max_results": 3,
            "include_domains": ["youtube.com"],
        }
    ]
    assert result.skipped == []
    assert result.items == [
        SourceItem(
            title=discovered.title,
            url=f"https://www.youtube.com/watch?v={VIDEO_ID}",
            score=discovered.score,
            summary="Hello world",
            source=Source.YOUTUBE,
            published_date=discovered.published_date,
        )
    ]


def test_transcript_excerpt_is_whitespace_normalized_and_bounded(monkeypatch) -> None:
    _install_discovery(monkeypatch, [_discovery_item(f"https://youtu.be/{VIDEO_ID}")])
    _install_api(monkeypatch, {VIDEO_ID: ["First\nline  with", "  spaced\t words  ", "x" * 3000]})

    result = youtube.search_youtube_videos("agentic")

    summary = result.items[0].summary
    assert summary.startswith("First line with spaced words x")
    assert "\n" not in summary and "  " not in summary
    assert len(summary) <= youtube.TRANSCRIPT_EXCERPT_MAX_CHARS


@pytest.mark.parametrize(
    "error",
    [
        TranscriptsDisabled(VIDEO_ID),
        NoTranscriptFound(VIDEO_ID, ["en"], "transcript listing"),
        VideoUnavailable(VIDEO_ID),
        VideoUnplayable(VIDEO_ID, "unplayable reason", []),
        AgeRestricted(VIDEO_ID),
        PoTokenRequired(VIDEO_ID),
    ],
)
def test_caption_failures_skip_only_that_video(monkeypatch, error: Exception) -> None:
    _install_discovery(
        monkeypatch,
        [
            _discovery_item(f"https://youtu.be/{VIDEO_ID}"),
            _discovery_item(f"https://youtu.be/{OTHER_ID}", title="Second"),
        ],
    )
    record = _install_api(monkeypatch, {VIDEO_ID: error, OTHER_ID: ["usable text"]})

    result = youtube.search_youtube_videos("agentic")

    assert [call["video_id"] for call in record["fetches"]] == [VIDEO_ID, OTHER_ID]
    assert [item.title for item in result.items] == ["Second"]
    assert result.skipped == [youtube.SkippedVideo(video_id=VIDEO_ID, reason=type(error).__name__)]


class _FutureTranscriptError(CouldNotRetrieveTranscript):
    """Stands in for an exception subclass added by a future library version."""


@pytest.mark.parametrize(
    "error",
    [
        RequestBlocked(VIDEO_ID),
        IpBlocked(VIDEO_ID),
        YouTubeRequestFailed(VIDEO_ID, requests.exceptions.HTTPError("boom")),
        YouTubeDataUnparsable(VIDEO_ID),
        requests.Timeout("timed out"),
        _FutureTranscriptError(VIDEO_ID),
    ],
)
def test_infrastructure_failures_propagate_and_stop_fetching(monkeypatch, error: Exception) -> None:
    _install_discovery(
        monkeypatch,
        [
            _discovery_item(f"https://youtu.be/{VIDEO_ID}"),
            _discovery_item(f"https://youtu.be/{OTHER_ID}"),
            _discovery_item(f"https://youtu.be/{THIRD_ID}"),
        ],
    )
    record = _install_api(monkeypatch, {VIDEO_ID: error})

    with pytest.raises(type(error)):
        youtube.search_youtube_videos("agentic")

    assert [call["video_id"] for call in record["fetches"]] == [VIDEO_ID]


@pytest.mark.parametrize(
    ("request_kwargs", "expected_timeout"),
    [
        ({}, youtube.TRANSCRIPT_TIMEOUT_SECONDS),
        ({"timeout": None}, youtube.TRANSCRIPT_TIMEOUT_SECONDS),
        ({"timeout": 5}, 5),
    ],
)
def test_timeout_session_enforces_finite_timeout(
    monkeypatch, request_kwargs: dict, expected_timeout: float
) -> None:
    sent: list[dict] = []

    def fake_send(self, prepared, **kwargs):
        sent.append(kwargs)
        return requests.Response()

    monkeypatch.setattr(requests.Session, "send", fake_send)

    with youtube._TimeoutSession() as session:
        session.get("http://example.invalid/", **request_kwargs)

    assert sent[0]["timeout"] == expected_timeout


def test_single_api_instance_and_session_closed_after_run(monkeypatch) -> None:
    closed: list[bool] = []

    class TrackingSession(youtube._TimeoutSession):
        def close(self) -> None:
            closed.append(True)
            super().close()

    monkeypatch.setattr(youtube, "_TimeoutSession", TrackingSession)
    _install_discovery(
        monkeypatch,
        [
            _discovery_item(f"https://youtu.be/{VIDEO_ID}"),
            _discovery_item(f"https://youtu.be/{OTHER_ID}"),
            _discovery_item(f"https://youtu.be/{THIRD_ID}"),
        ],
    )
    record = _install_api(monkeypatch, {VIDEO_ID: ["a"], OTHER_ID: ["b"], THIRD_ID: ["c"]})

    result = youtube.search_youtube_videos("agentic")

    assert len(result.items) == 3
    assert len(record["clients"]) == 1
    assert isinstance(record["clients"][0], TrackingSession)
    assert len(record["fetches"]) == 3
    assert closed == [True]


def test_session_closed_when_infrastructure_failure_escapes(monkeypatch) -> None:
    closed: list[bool] = []

    class TrackingSession(youtube._TimeoutSession):
        def close(self) -> None:
            closed.append(True)
            super().close()

    monkeypatch.setattr(youtube, "_TimeoutSession", TrackingSession)
    _install_discovery(monkeypatch, [_discovery_item(f"https://youtu.be/{VIDEO_ID}")])
    _install_api(monkeypatch, {VIDEO_ID: IpBlocked(VIDEO_ID)})

    with pytest.raises(IpBlocked):
        youtube.search_youtube_videos("agentic")

    assert closed == [True]


def test_skip_logging_exposes_id_and_class_but_never_message(monkeypatch, caplog) -> None:
    _install_discovery(monkeypatch, [_discovery_item(f"https://youtu.be/{VIDEO_ID}")])
    error = VideoUnplayable(VIDEO_ID, "DISTINCTIVE-PROVIDER-DETAIL", ["raw payload line"])
    _install_api(monkeypatch, {VIDEO_ID: error})

    with caplog.at_level("WARNING", logger=youtube.logger.name):
        youtube.search_youtube_videos("agentic")

    messages = [record.getMessage() for record in caplog.records]
    assert any(VIDEO_ID in message and "VideoUnplayable" in message for message in messages)
    assert "DISTINCTIVE-PROVIDER-DETAIL" not in caplog.text
    assert "raw payload line" not in caplog.text


def test_non_video_discovery_urls_are_dropped_silently(monkeypatch) -> None:
    _install_discovery(
        monkeypatch,
        [
            _discovery_item("https://www.youtube.com/channel/UC12345"),
            _discovery_item("https://www.youtube.com/playlist?list=PL123"),
            _discovery_item(f"https://youtu.be/{VIDEO_ID}"),
        ],
    )
    record = _install_api(monkeypatch, {VIDEO_ID: ["usable text"]})

    result = youtube.search_youtube_videos("agentic")

    assert [call["video_id"] for call in record["fetches"]] == [VIDEO_ID]
    assert len(result.items) == 1
    assert result.skipped == []


def test_duplicate_video_ids_fetch_transcript_once(monkeypatch) -> None:
    _install_discovery(
        monkeypatch,
        [
            _discovery_item(f"https://www.youtube.com/watch?v={VIDEO_ID}", title="First"),
            _discovery_item(f"https://youtu.be/{VIDEO_ID}", title="Duplicate"),
        ],
    )
    record = _install_api(monkeypatch, {VIDEO_ID: ["usable text"]})

    result = youtube.search_youtube_videos("agentic")

    assert [call["video_id"] for call in record["fetches"]] == [VIDEO_ID]
    assert [item.title for item in result.items] == ["First"]


def test_transcript_limit_truncates_without_recording_skips(monkeypatch) -> None:
    _install_discovery(
        monkeypatch,
        [
            _discovery_item(f"https://youtu.be/{video_id}")
            for video_id in (VIDEO_ID, OTHER_ID, THIRD_ID, FOURTH_ID)
        ],
    )
    record = _install_api(monkeypatch, {VIDEO_ID: ["a"], OTHER_ID: ["b"]})

    result = youtube.search_youtube_videos("agentic", max_transcripts=2)

    assert [call["video_id"] for call in record["fetches"]] == [VIDEO_ID, OTHER_ID]
    assert len(result.items) == 2
    assert result.skipped == []


def test_empty_transcript_is_recorded_as_skipped(monkeypatch) -> None:
    _install_discovery(monkeypatch, [_discovery_item(f"https://youtu.be/{VIDEO_ID}")])
    _install_api(monkeypatch, {VIDEO_ID: ["   ", "\n\t"]})

    result = youtube.search_youtube_videos("agentic")

    assert result.items == []
    assert result.skipped == [youtube.SkippedVideo(video_id=VIDEO_ID, reason="empty_transcript")]


def test_discovery_failure_propagates_before_transcripts(monkeypatch) -> None:
    def fail_search(*args, **kwargs):
        raise RuntimeError("TAVILY_API_KEY not set — check .env")

    monkeypatch.setattr(youtube, "search_articles", fail_search)

    with pytest.raises(RuntimeError):
        youtube.search_youtube_videos("agentic")


@pytest.mark.parametrize("max_results", [0, -1, youtube.MAX_RESULTS + 1, 1.5, True])
def test_search_rejects_invalid_max_results(max_results) -> None:
    with pytest.raises(ValueError, match="max_results"):
        youtube.search_youtube_videos("agentic", max_results=max_results)


@pytest.mark.parametrize("max_transcripts", [0, -1, youtube.MAX_TRANSCRIPTS + 1, 1.5, True])
def test_search_rejects_invalid_max_transcripts(max_transcripts) -> None:
    with pytest.raises(ValueError, match="max_transcripts"):
        youtube.search_youtube_videos("agentic", max_transcripts=max_transcripts)
