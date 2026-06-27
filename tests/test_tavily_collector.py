"""Tests for pulse.collectors.tavily — no API calls."""

from __future__ import annotations

from pulse.collectors.tavily import parse_tavily_results
from pulse.models import Article, Source

MOCK_RAW_RESULTS = [
    {
        "title": "LangGraph 2.0 released — streaming support",
        "url": "https://news.ycombinator.com/item?id=99999",
        "content": "LangGraph 2.0 introduces streaming support and improved state management...",
        "score": 0.87,
        "published_date": "2026-06-20",
    },
    {
        "title": "FastMCP hits 1M downloads",
        "url": "https://news.ycombinator.com/item?id=88888",
        "content": "The FastMCP library has reached 1 million downloads on PyPI...",
        "score": 0.91,
        "published_date": "2026-06-25",
    },
]


def test_parse_tavily_results_returns_correct_count() -> None:
    articles = parse_tavily_results(MOCK_RAW_RESULTS, Source.HACKER_NEWS)
    assert len(articles) == 2


def test_parse_tavily_results_returns_article_instances() -> None:
    articles = parse_tavily_results(MOCK_RAW_RESULTS, Source.HACKER_NEWS)
    for a in articles:
        assert isinstance(a, Article)


def test_parse_tavily_results_sets_source() -> None:
    articles = parse_tavily_results(MOCK_RAW_RESULTS, Source.ARXIV)
    assert all(a.source == Source.ARXIV for a in articles)


def test_parse_tavily_results_maps_title_and_url() -> None:
    articles = parse_tavily_results(MOCK_RAW_RESULTS, Source.HACKER_NEWS)
    assert articles[0].title == "LangGraph 2.0 released — streaming support"
    assert articles[1].url == "https://news.ycombinator.com/item?id=88888"


def test_parse_tavily_results_maps_score_as_float() -> None:
    articles = parse_tavily_results(MOCK_RAW_RESULTS, Source.HACKER_NEWS)
    assert articles[0].score == 0.87
    assert isinstance(articles[0].score, float)


def test_parse_tavily_results_maps_published_date() -> None:
    articles = parse_tavily_results(MOCK_RAW_RESULTS, Source.HACKER_NEWS)
    assert articles[0].published_date == "2026-06-20"


def test_parse_tavily_results_truncates_content_to_500_chars() -> None:
    raw = [{"title": "T", "url": "u", "content": "x" * 1000, "score": 0.5}]
    articles = parse_tavily_results(raw, Source.HACKER_NEWS)
    assert len(articles[0].summary) <= 500


def test_parse_tavily_results_handles_missing_score() -> None:
    raw = [{"title": "T", "url": "https://hn.com/1"}]
    articles = parse_tavily_results(raw, Source.HACKER_NEWS)
    assert articles[0].score == 0.0


def test_parse_tavily_results_handles_missing_content() -> None:
    raw = [{"title": "T", "url": "u"}]
    articles = parse_tavily_results(raw, Source.HACKER_NEWS)
    assert articles[0].summary == ""


def test_parse_tavily_results_handles_none_content() -> None:
    raw = [{"title": "T", "url": "u", "content": None, "score": 0.5}]
    articles = parse_tavily_results(raw, Source.HACKER_NEWS)
    assert articles[0].summary == ""


def test_parse_tavily_results_handles_none_score() -> None:
    raw = [{"title": "T", "url": "u", "score": None}]
    articles = parse_tavily_results(raw, Source.HACKER_NEWS)
    assert articles[0].score == 0.0


def test_parse_tavily_results_defaults_missing_title_to_untitled() -> None:
    raw = [{"url": "u", "score": 0.5}]
    articles = parse_tavily_results(raw, Source.HACKER_NEWS)
    assert articles[0].title == "Untitled"


def test_parse_tavily_results_defaults_none_title_to_untitled() -> None:
    raw = [{"title": None, "url": "u", "score": 0.5}]
    articles = parse_tavily_results(raw, Source.HACKER_NEWS)
    assert articles[0].title == "Untitled"


def test_parse_tavily_results_handles_missing_published_date() -> None:
    raw = [{"title": "T", "url": "u"}]
    articles = parse_tavily_results(raw, Source.HACKER_NEWS)
    assert articles[0].published_date == ""


def test_parse_tavily_results_empty_input() -> None:
    assert parse_tavily_results([], Source.HACKER_NEWS) == []
