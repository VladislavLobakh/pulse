"""Tests for the display boundary's analysis rendering.

Only display-owned invariants live here — the item/summary formatting itself is
covered end-to-end through test_main.py's capsys assertions.
"""

from __future__ import annotations

import pytest

from pulse.display import print_analysis_summary, print_items
from pulse.models import Source, SourceItem
from pulse.patterns.topic_signal import (
    AnalysisRunResult,
    AnalysisStatus,
    EventType,
    TopicSignal,
    TopicSignalResult,
)


def _item(url: str, title: str = "t") -> SourceItem:
    return SourceItem(title=title, url=url, score=0.9, summary="s", source=Source.ARXIV)


def _ok(item: SourceItem) -> TopicSignalResult:
    return TopicSignalResult(
        item=item,
        status=AnalysisStatus.SUCCESS,
        signal=TopicSignal(
            topic="Claude Opus 4.8",
            event_type=EventType.RELEASE,
            key_change="Made generally available.",
            relevance=0.95,
            confidence=0.9,
            evidence="The item says it shipped today.",
        ),
    )


def test_length_mismatch_raises() -> None:
    items = [_item("https://a.example/1"), _item("https://a.example/2")]

    with pytest.raises(ValueError):
        print_items(items, [_ok(items[0])])


def test_same_length_order_mismatch_raises() -> None:
    items = [_item("https://a.example/1"), _item("https://a.example/2")]
    permuted = [_ok(items[1]), _ok(items[0])]

    with pytest.raises(ValueError):
        print_items(items, permuted)


def test_failed_result_renders_only_the_error_code(capsys) -> None:
    item = _item("https://a.example/1")
    failed = TopicSignalResult(
        item=item, status=AnalysisStatus.FAILED, error="ModelsExhaustedError"
    )

    print_items([item], [failed])

    out = capsys.readouterr().out
    assert "analysis: FAILED (ModelsExhaustedError)" in out
    assert "relevance" not in out
    assert "evidence" not in out


def test_analysis_none_renders_items_without_an_analysis_section(capsys) -> None:
    item = _item("https://a.example/1", title="HN item")

    print_items([item])

    out = capsys.readouterr().out
    assert "1. HN item" in out
    assert "url:   https://a.example/1" in out
    assert "analysis" not in out
    assert "topic:" not in out


def test_summary_reports_derived_counts(capsys) -> None:
    item = _item("https://a.example/1")
    run = AnalysisRunResult.completed(
        [_ok(item), TopicSignalResult(item=item, status=AnalysisStatus.FAILED, error="X")]
    )

    print_analysis_summary(run)

    assert "Analysis: PARTIAL — 1 analyzed, 1 failed" in capsys.readouterr().out


def test_summary_reports_a_shared_error_instead_of_counts(capsys) -> None:
    print_analysis_summary(AnalysisRunResult.aborted("ProviderConfigurationError"))

    out = capsys.readouterr().out
    assert "Analysis: FAILED — unavailable (ProviderConfigurationError)" in out
    assert "analyzed" not in out
