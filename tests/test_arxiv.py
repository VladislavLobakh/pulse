"""Tests for the ArXiv source runner and its generic coordinator integration."""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET

import httpx
import pytest

import pulse.agents.arxiv as arxiv_agent
from pulse.collectors.arxiv import ArxivAPIError
from pulse.models import Source, SourceItem
from pulse.patterns.parallel import RunStatus, run_sources

PAPER = SourceItem(
    title="Agentic Retrieval Systems",
    url="https://arxiv.org/abs/2502.01234v1",
    score=0.0,
    summary="An abstract.",
    source=Source.ARXIV,
    published_date="2025-02-03",
)


def test_runner_returns_success_for_valid_items(monkeypatch) -> None:
    captured = {}

    def fake_search(query, *, max_results, pdf_enrichment_limit):
        captured.update(
            query=query,
            max_results=max_results,
            pdf_enrichment_limit=pdf_enrichment_limit,
        )
        return [PAPER]

    monkeypatch.setattr(arxiv_agent, "search_arxiv_papers", fake_search)

    output = arxiv_agent.arxiv_runner(max_results=3, pdf_enrichment_limit=1).run(
        'agentic "tool use"'
    )

    assert captured == {
        "query": 'agentic "tool use"',
        "max_results": 3,
        "pdf_enrichment_limit": 1,
    }
    assert output.items == [PAPER]
    assert output.status is RunStatus.SUCCESS
    assert output.error is None


def test_runner_maps_valid_empty_result_to_partial(monkeypatch) -> None:
    monkeypatch.setattr(arxiv_agent, "search_arxiv_papers", lambda *args, **kwargs: [])

    output = arxiv_agent.arxiv_runner().run("agentic")

    assert output.items == []
    assert output.status is RunStatus.PARTIAL
    assert output.error == "no_results"


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
        url="https://arxiv.org/abs/2502.99999",
        score=0.0,
        summary="Extra.",
        source=Source.ARXIV,
    )
    monkeypatch.setattr(
        arxiv_agent,
        "search_arxiv_papers",
        lambda *args, **kwargs: [wrong_source, PAPER, extra],
    )

    output = arxiv_agent.arxiv_runner(max_results=1).run("agentic")

    assert output.items == [PAPER]
    assert all(item.source is Source.ARXIV for item in output.items)


def test_runner_works_through_source_neutral_coordinator(monkeypatch) -> None:
    monkeypatch.setattr(
        arxiv_agent,
        "search_arxiv_papers",
        lambda *args, **kwargs: [PAPER],
    )

    result = asyncio.run(run_sources("agentic", [arxiv_agent.arxiv_runner(max_results=1)]))

    assert result.status is RunStatus.SUCCESS
    assert result.items == [PAPER]
    assert result.results[0].source is Source.ARXIV


def _http_error() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://export.arxiv.org/api/query")
    response = httpx.Response(503, request=request)
    return httpx.HTTPStatusError("failed", request=request, response=response)


@pytest.mark.parametrize(
    "error",
    [
        _http_error(),
        httpx.ReadTimeout("timed out"),
        ET.ParseError("invalid XML"),
        ArxivAPIError("error entry"),
    ],
)
def test_source_failures_become_failed_coordinator_results(monkeypatch, error: Exception) -> None:
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(arxiv_agent, "search_arxiv_papers", fail)

    result = asyncio.run(run_sources("agentic", [arxiv_agent.arxiv_runner()]))

    assert result.status is RunStatus.FAILED
    assert result.items == []
    assert result.results[0].status is RunStatus.FAILED
    assert result.results[0].error == type(error).__name__
