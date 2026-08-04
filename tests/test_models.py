"""Tests for pulse.models."""

from __future__ import annotations

from dataclasses import asdict

from pulse.models import Source, SourceItem


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
    assert len(Source) == 4
    assert {s.value for s in Source} == {
        "hacker_news",
        "arxiv",
        "youtube",
        "newsletter",
    }
