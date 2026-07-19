"""Tests for the YouTube source runner and its generic coordinator integration."""

from __future__ import annotations

import asyncio

import pytest
from youtube_transcript_api import IpBlocked, TranscriptsDisabled

import pulse.agents.youtube as youtube_agent
import pulse.collectors.youtube as youtube_collector
from pulse.collectors.youtube import SkippedVideo, YouTubeCollectResult
from pulse.models import Source, SourceItem
from pulse.patterns.parallel import RunStatus, SourceOutput, SourceRunner, run_sources

VIDEO_ID = "dQw4w9WgXcQ"
OTHER_ID = "abcdefghijk"

VIDEO_ITEM = SourceItem(
    title="Agentic AI talk",
    url=f"https://www.youtube.com/watch?v={VIDEO_ID}",
    score=0.9,
    summary="A transcript excerpt.",
    source=Source.YOUTUBE,
    published_date="2026-01-05",
)

HN_ITEM = SourceItem(
    title="Agentic retrieval discussion",
    url="https://news.ycombinator.com/item?id=12345",
    score=0.8,
    summary="A Hacker News discussion.",
    source=Source.HACKER_NEWS,
)


def test_runner_returns_success_for_items_without_skips(monkeypatch) -> None:
    captured = {}

    def fake_search(query, *, max_results, max_transcripts):
        captured.update(query=query, max_results=max_results, max_transcripts=max_transcripts)
        return YouTubeCollectResult(items=[VIDEO_ITEM])

    monkeypatch.setattr(youtube_agent, "search_youtube_videos", fake_search)

    output = youtube_agent.youtube_runner(max_results=3, max_transcripts=2).run("agentic ai")

    assert captured == {"query": "agentic ai", "max_results": 3, "max_transcripts": 2}
    assert output.items == [VIDEO_ITEM]
    assert output.status is RunStatus.SUCCESS
    assert output.error is None


def test_runner_maps_empty_discovery_to_partial_no_results(monkeypatch) -> None:
    monkeypatch.setattr(
        youtube_agent,
        "search_youtube_videos",
        lambda *args, **kwargs: YouTubeCollectResult(),
    )

    output = youtube_agent.youtube_runner().run("agentic")

    assert output.items == []
    assert output.status is RunStatus.PARTIAL
    assert output.error == "no_results"


def test_runner_maps_all_skipped_to_partial_no_transcripts(monkeypatch) -> None:
    monkeypatch.setattr(
        youtube_agent,
        "search_youtube_videos",
        lambda *args, **kwargs: YouTubeCollectResult(
            skipped=[SkippedVideo(video_id=VIDEO_ID, reason="TranscriptsDisabled")]
        ),
    )

    output = youtube_agent.youtube_runner().run("agentic")

    assert output.items == []
    assert output.status is RunStatus.PARTIAL
    assert output.error == "no_transcripts"


def test_runner_mixed_usable_and_unusable_is_partial_with_items(monkeypatch) -> None:
    monkeypatch.setattr(
        youtube_agent,
        "search_youtube_videos",
        lambda *args, **kwargs: YouTubeCollectResult(
            items=[VIDEO_ITEM],
            skipped=[SkippedVideo(video_id=OTHER_ID, reason="NoTranscriptFound")],
        ),
    )

    output = youtube_agent.youtube_runner().run("agentic")

    assert output.items == [VIDEO_ITEM]
    assert output.status is RunStatus.PARTIAL
    assert output.error == "skipped_videos"
    assert OTHER_ID not in output.error


def test_runner_enforces_source_membership_and_bound(monkeypatch) -> None:
    extra = SourceItem(
        title="Extra",
        url=f"https://www.youtube.com/watch?v={OTHER_ID}",
        score=0.5,
        summary="Another excerpt.",
        source=Source.YOUTUBE,
    )
    monkeypatch.setattr(
        youtube_agent,
        "search_youtube_videos",
        lambda *args, **kwargs: YouTubeCollectResult(items=[HN_ITEM, VIDEO_ITEM, extra]),
    )

    output = youtube_agent.youtube_runner(max_results=1).run("agentic")

    assert output.items == [VIDEO_ITEM]
    assert all(item.source is Source.YOUTUBE for item in output.items)


def test_runner_works_through_source_neutral_coordinator(monkeypatch) -> None:
    monkeypatch.setattr(
        youtube_agent,
        "search_youtube_videos",
        lambda *args, **kwargs: YouTubeCollectResult(items=[VIDEO_ITEM]),
    )

    other_runner = SourceRunner(
        source=Source.HACKER_NEWS,
        run=lambda query: SourceOutput(items=[HN_ITEM], status=RunStatus.SUCCESS),
    )
    result = asyncio.run(
        run_sources("agentic", [youtube_agent.youtube_runner(max_results=1), other_runner])
    )

    assert result.status is RunStatus.SUCCESS
    assert result.items == [VIDEO_ITEM, HN_ITEM]
    assert [source_result.source for source_result in result.results] == [
        Source.YOUTUBE,
        Source.HACKER_NEWS,
    ]


def _install_collector_run(monkeypatch, transcripts: dict[str, list[str] | Exception]) -> None:
    monkeypatch.setattr(
        youtube_collector,
        "search_articles",
        lambda *args, **kwargs: [
            SourceItem(
                title=f"Video {video_id}",
                url=f"https://youtu.be/{video_id}",
                score=0.7,
                summary="A search snippet.",
                source=Source.YOUTUBE,
            )
            for video_id in transcripts
        ],
    )

    class _Snippet:
        def __init__(self, text: str) -> None:
            self.text = text

    class _Fetched:
        def __init__(self, texts: list[str]) -> None:
            self.snippets = [_Snippet(text) for text in texts]

    class FakeApi:
        def __init__(self, http_client=None) -> None:
            pass

        def fetch(self, video_id, languages=None):
            outcome = transcripts[video_id]
            if isinstance(outcome, Exception):
                raise outcome
            return _Fetched(outcome)

    monkeypatch.setattr(youtube_collector, "YouTubeTranscriptApi", FakeApi)


def test_no_subtitles_never_escapes_source_boundary(monkeypatch) -> None:
    _install_collector_run(
        monkeypatch,
        {VIDEO_ID: TranscriptsDisabled(VIDEO_ID), OTHER_ID: ["usable transcript text"]},
    )

    result = asyncio.run(run_sources("agentic", [youtube_agent.youtube_runner()]))

    assert result.status is RunStatus.PARTIAL
    assert result.results[0].status is RunStatus.PARTIAL
    assert result.results[0].error == "skipped_videos"
    assert [item.url for item in result.items] == [f"https://www.youtube.com/watch?v={OTHER_ID}"]


@pytest.mark.parametrize(
    "error",
    [IpBlocked(VIDEO_ID), RuntimeError("TAVILY_API_KEY not set — check .env")],
)
def test_source_failures_become_failed_coordinator_results(monkeypatch, error: Exception) -> None:
    if isinstance(error, RuntimeError):

        def fail_search(*args, **kwargs):
            raise error

        monkeypatch.setattr(youtube_collector, "search_articles", fail_search)
    else:
        _install_collector_run(monkeypatch, {VIDEO_ID: error})

    result = asyncio.run(run_sources("agentic", [youtube_agent.youtube_runner()]))

    assert result.status is RunStatus.FAILED
    assert result.items == []
    assert result.results[0].status is RunStatus.FAILED
    assert result.results[0].error == type(error).__name__
    assert "TAVILY_API_KEY" not in repr(result)
