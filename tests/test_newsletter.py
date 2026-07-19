"""Tests for the newsletter source runner and its generic coordinator integration."""

from __future__ import annotations

import asyncio

import httpx
import pytest

import pulse.agents.newsletter as newsletter_agent
from pulse.collectors.newsletter import NewsletterFeedError, NewsletterFetchResult
from pulse.models import Source, SourceItem
from pulse.patterns.parallel import RunStatus, SourceOutput, SourceRunner, run_sources

ITEM = SourceItem(
    title="Exploring agentic workflows",
    url="https://simonwillison.net/2026/Feb/3/agentic/",
    score=1.0,
    summary="[Simon Willison] Notes on agentic workflows.",
    source=Source.NEWSLETTER,
    published_date="2026-02-03",
)

HN_ITEM = SourceItem(
    title="Agentic retrieval discussion",
    url="https://news.ycombinator.com/item?id=12345",
    score=0.8,
    summary="A Hacker News discussion.",
    source=Source.HACKER_NEWS,
)


def _fetch_result(
    items: list[SourceItem],
    failed_feeds: tuple[str, ...] = (),
) -> NewsletterFetchResult:
    return NewsletterFetchResult(items=items, failed_feeds=failed_feeds)


def test_runner_returns_success_for_valid_items(monkeypatch) -> None:
    captured = {}

    def fake_fetch(query, *, max_results):
        captured.update(query=query, max_results=max_results)
        return _fetch_result([ITEM])

    monkeypatch.setattr(newsletter_agent, "fetch_newsletter_items", fake_fetch)

    output = newsletter_agent.newsletter_runner(max_results=3).run("agentic workflows")

    assert captured == {"query": "agentic workflows", "max_results": 3}
    assert output.items == [ITEM]
    assert output.status is RunStatus.SUCCESS
    assert output.error is None


def test_runner_maps_valid_empty_result_to_partial(monkeypatch) -> None:
    monkeypatch.setattr(
        newsletter_agent,
        "fetch_newsletter_items",
        lambda *args, **kwargs: _fetch_result([]),
    )

    output = newsletter_agent.newsletter_runner().run("agentic")

    assert output.items == []
    assert output.status is RunStatus.PARTIAL
    assert output.error == "no_results"


def test_runner_keeps_items_and_reports_partial_when_a_feed_failed(monkeypatch) -> None:
    monkeypatch.setattr(
        newsletter_agent,
        "fetch_newsletter_items",
        lambda *args, **kwargs: _fetch_result([ITEM], failed_feeds=("Latent Space",)),
    )

    output = newsletter_agent.newsletter_runner().run("agentic")

    assert output.items == [ITEM]
    assert output.status is RunStatus.PARTIAL
    assert output.error == "partial_feed_failure"


def test_runner_reports_partial_feed_failure_even_without_items(monkeypatch) -> None:
    monkeypatch.setattr(
        newsletter_agent,
        "fetch_newsletter_items",
        lambda *args, **kwargs: _fetch_result([], failed_feeds=("Latent Space",)),
    )

    output = newsletter_agent.newsletter_runner().run("agentic")

    assert output.items == []
    assert output.status is RunStatus.PARTIAL
    assert output.error == "partial_feed_failure"


def test_runner_enforces_source_membership_and_bound(monkeypatch) -> None:
    wrong_source = SourceItem(
        title="Wrong",
        url="https://example.com",
        score=1.0,
        summary="Wrong source.",
        source=Source.HACKER_NEWS,
    )
    extra = SourceItem(
        title="Extra",
        url="https://www.latent.space/p/extra",
        score=0.5,
        summary="[Latent Space] Extra.",
        source=Source.NEWSLETTER,
    )
    monkeypatch.setattr(
        newsletter_agent,
        "fetch_newsletter_items",
        lambda *args, **kwargs: _fetch_result([wrong_source, ITEM, extra]),
    )

    output = newsletter_agent.newsletter_runner(max_results=1).run("agentic")

    assert output.items == [ITEM]
    assert all(item.source is Source.NEWSLETTER for item in output.items)


def test_runner_works_through_source_neutral_coordinator(monkeypatch) -> None:
    monkeypatch.setattr(
        newsletter_agent,
        "fetch_newsletter_items",
        lambda *args, **kwargs: _fetch_result([ITEM]),
    )

    other_runner = SourceRunner(
        source=Source.HACKER_NEWS,
        run=lambda query: SourceOutput(items=[HN_ITEM], status=RunStatus.SUCCESS),
    )
    result = asyncio.run(
        run_sources(
            "agentic",
            [newsletter_agent.newsletter_runner(max_results=1), other_runner],
        )
    )

    assert result.status is RunStatus.SUCCESS
    assert result.items == [ITEM, HN_ITEM]
    assert [source_result.source for source_result in result.results] == [
        Source.NEWSLETTER,
        Source.HACKER_NEWS,
    ]
    assert all(source_result.status is RunStatus.SUCCESS for source_result in result.results)


def _http_error() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://www.latent.space/feed")
    response = httpx.Response(503, request=request)
    return httpx.HTTPStatusError("failed", request=request, response=response)


@pytest.mark.parametrize(
    "error",
    [
        _http_error(),
        httpx.ReadTimeout("timed out"),
        NewsletterFeedError("all newsletter feeds failed"),
    ],
)
def test_source_failures_become_failed_coordinator_results(monkeypatch, error: Exception) -> None:
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(newsletter_agent, "fetch_newsletter_items", fail)

    other_runner = SourceRunner(
        source=Source.HACKER_NEWS,
        run=lambda query: SourceOutput(items=[HN_ITEM], status=RunStatus.SUCCESS),
    )
    result = asyncio.run(
        run_sources("agentic", [newsletter_agent.newsletter_runner(), other_runner])
    )

    assert result.status is RunStatus.PARTIAL
    assert result.items == [HN_ITEM]
    assert result.results[0].status is RunStatus.FAILED
    assert result.results[0].error == type(error).__name__
    assert result.results[1].status is RunStatus.SUCCESS
