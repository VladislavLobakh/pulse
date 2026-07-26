"""Reviewed golden examples for the topic_signal analyzer.

Each case pairs a realistic SourceItem with a human-reviewed TopicSignal that
a correct extraction over that kind of content could plausibly produce. These
are analyzer *plumbing* fixtures, not model-quality evaluations: the
assertions only check that analyze_items passes the item and signal through
unchanged (validated, ordered, not corrupted) — they do not grade whether the
signal is the "right" judgment for the content. Judging extraction quality
against a live model belongs in pulse/evals/, which needs network access and
is deliberately out of scope for these deterministic tests.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from pulse.models import Source, SourceItem
from pulse.patterns.topic_signal import (
    AnalysisStatus,
    EventType,
    TopicSignal,
    analyze_items,
)


@dataclass
class GoldenCase:
    id: str
    item: SourceItem
    signal: TopicSignal
    notes: str


GOLDEN_CASES = [
    GoldenCase(
        id="new_release",
        item=SourceItem(
            title="Anthropic ships Claude Opus 4.8",
            url="https://a.example/opus-4-8",
            score=0.95,
            summary="Anthropic announced the general availability of Claude "
            "Opus 4.8 today, its newest flagship model.",
            source=Source.HACKER_NEWS,
            published_date="2026-07-20",
        ),
        signal=TopicSignal(
            topic="Claude Opus 4.8",
            event_type=EventType.RELEASE,
            key_change="Anthropic made Claude Opus 4.8 generally available.",
            relevance=0.95,
            confidence=0.9,
            evidence="The item states Opus 4.8 was announced as generally available today.",
        ),
        notes="Exercises event_type=RELEASE for a freshly announced item.",
    ),
    GoldenCase(
        id="older_foundational_item",
        item=SourceItem(
            title="Attention Is All You Need",
            url="https://a.example/transformer-paper",
            score=0.7,
            summary="The 2017 paper introducing the Transformer architecture, "
            "foundational to modern large language models.",
            source=Source.ARXIV,
            published_date="2017-06-12",
        ),
        signal=TopicSignal(
            topic="Transformer architecture",
            event_type=EventType.RESEARCH,
            key_change="No new change — this is the original, long-established "
            "paper the field's later work builds on.",
            relevance=0.6,
            confidence=0.85,
            evidence="The summary itself describes the paper as foundational and dated 2017.",
        ),
        notes="Exercises event_type=RESEARCH for old, well-established content.",
    ),
    GoldenCase(
        id="repeated_announcement",
        item=SourceItem(
            title="Reminder: our API price cut is now live",
            url="https://a.example/price-cut-recap",
            score=0.4,
            summary="As previously announced last month, our reduced API "
            "pricing has now taken effect for all customers.",
            source=Source.NEWSLETTER,
            published_date="2026-07-15",
        ),
        signal=TopicSignal(
            topic="API pricing",
            event_type=EventType.RECAP,
            key_change="Restates a price cut already announced last month; "
            "nothing new beyond confirming it took effect.",
            relevance=0.5,
            confidence=0.8,
            evidence="The item's own wording says 'as previously announced last month'.",
        ),
        notes="Exercises event_type=RECAP judged from the item's own "
        "recap-style wording, not by comparison to other items.",
    ),
    GoldenCase(
        id="unknown_category",
        item=SourceItem(
            title="thoughts?",
            url="https://a.example/vague-post",
            score=0.2,
            summary="just something I've been thinking about lately, curious what others think",
            source=Source.TWITTER,
        ),
        signal=TopicSignal(
            topic="unspecified",
            event_type=EventType.UNKNOWN,
            key_change="No concrete change or announcement is identifiable from the content.",
            relevance=0.3,
            confidence=0.2,
            evidence="The title and summary contain no concrete subject or claim to categorize.",
        ),
        notes="Exercises event_type=UNKNOWN for genuinely uncategorizable content.",
    ),
    GoldenCase(
        id="off_topic_item",
        item=SourceItem(
            title="Best cast iron skillet seasoning tips",
            url="https://a.example/skillet-tips",
            score=0.6,
            summary="A discussion thread on maintaining cast iron cookware, "
            "unrelated to AI or software.",
            source=Source.HACKER_NEWS,
            published_date="2026-07-10",
        ),
        signal=TopicSignal(
            topic="cast iron cookware maintenance",
            event_type=EventType.DISCUSSION,
            key_change="A cookware maintenance discussion; no AI-related development to report.",
            relevance=0.05,
            confidence=0.9,
            evidence="The content is squarely about cookware care, with no "
            "connection to the query's subject.",
        ),
        notes="Exercises low relevance (not low confidence) for off-topic "
        "content — the extraction itself is clear, just irrelevant to the "
        "query.",
    ),
    GoldenCase(
        id="sparse_low_confidence_item",
        item=SourceItem(
            title="update",
            url="https://a.example/sparse-update",
            score=0.3,
            summary="minor fixes",
            source=Source.YOUTUBE,
        ),
        signal=TopicSignal(
            topic="unspecified update",
            event_type=EventType.TUTORIAL,
            key_change="Some unspecified minor fixes; no concrete detail given.",
            relevance=0.4,
            confidence=0.15,
            evidence="Title and summary are too thin ('update', 'minor "
            "fixes') to support a confident extraction.",
        ),
        notes="Exercises low confidence for a thin, low-information item.",
    ),
]


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[c.id for c in GOLDEN_CASES])
def test_golden_case_passes_through_analyzer_unchanged(case: GoldenCase) -> None:
    def fake(*, messages: list[dict], response_model: type[TopicSignal]) -> TopicSignal:
        # Guards against _build_messages silently dropping the item's
        # content — without this the fake would pass regardless.
        content = messages[1]["content"]
        assert case.item.title in content
        assert case.item.summary in content
        assert case.item.url in content
        return case.signal

    results = asyncio.run(analyze_items("original query", [case.item], fake))

    assert len(results) == 1
    result = results[0]
    assert result.item == case.item
    assert result.status is AnalysisStatus.SUCCESS
    assert result.signal == case.signal
    assert result.error is None


def test_golden_examples_cover_every_requested_category() -> None:
    assert {case.id for case in GOLDEN_CASES} == {
        "new_release",
        "older_foundational_item",
        "repeated_announcement",
        "unknown_category",
        "off_topic_item",
        "sparse_low_confidence_item",
    }
