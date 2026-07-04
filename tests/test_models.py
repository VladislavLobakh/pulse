"""Tests for pulse.models."""

from __future__ import annotations

from dataclasses import asdict

import pytest
from pydantic import ValidationError

from pulse.models import ReasonDecision, Source, SourceBatchScore, SourceItem


def test_source_item_construction_with_all_fields() -> None:
    a = SourceItem(
        title="T",
        url="https://hn.com/1",
        score=0.5,
        summary="S",
        source=Source.HACKER_NEWS,
    )
    assert a.title == "T"
    assert a.url == "https://hn.com/1"
    assert a.score == 0.5
    assert a.summary == "S"
    assert a.source == Source.HACKER_NEWS


def test_source_item_has_correct_default_published_date() -> None:
    a = SourceItem(title="T", url="u", score=0.5, summary="s", source=Source.ARXIV)
    assert a.published_date == ""


def test_source_item_serializes_to_dict() -> None:
    a = SourceItem(title="T", url="u", score=0.5, summary="s", source=Source.YOUTUBE)
    d = asdict(a)
    assert set(d.keys()) == {"title", "url", "score", "summary", "source", "published_date"}


def test_source_enum_serializes_as_plain_string() -> None:
    a = SourceItem(title="T", url="u", score=0.5, summary="s", source=Source.HACKER_NEWS)
    d = asdict(a)
    assert d["source"] == "hacker_news"
    assert isinstance(d["source"], str)


def test_source_enum_lists_all_sources() -> None:
    assert len(Source) == 5
    assert {s.value for s in Source} == {
        "hacker_news",
        "arxiv",
        "youtube",
        "newsletter",
        "twitter",
    }


def test_reason_decision_validates() -> None:
    decision = ReasonDecision(thought="look for AI news", query="AI LLM site:news.ycombinator.com")
    assert decision.thought == "look for AI news"
    assert decision.query == "AI LLM site:news.ycombinator.com"


def test_source_batch_score_validates() -> None:
    score = SourceBatchScore(relevance=0.5, novelty=0.6, quality=0.7)
    assert score.overall == pytest.approx(0.6)


def test_source_batch_score_rejects_out_of_range_relevance() -> None:
    with pytest.raises(ValidationError):
        SourceBatchScore(relevance=1.5, novelty=0.5, quality=0.5)


def test_source_batch_score_rejects_negative_score() -> None:
    with pytest.raises(ValidationError):
        SourceBatchScore(relevance=0.5, novelty=-0.1, quality=0.5)
