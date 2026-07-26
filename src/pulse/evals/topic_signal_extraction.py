"""Live extraction-quality eval for the topic_signal analyzer.

topic_signal has no wired-in agent yet, so there is no production model list
to regress against — this script defines its own chain and calls
`analyze_items` directly, the same public entry point any future caller would
use. Needs OPENROUTER_API_KEY; network use is why this is a script, not a
pytest test.

This is the first time the prompt and schema (including the `EventType` enum
field — untested against a real Instructor/litellm JSON-mode round-trip)
run against a real model. Prints every field for manual review: judgments
like the RECAP/DISCUSSION boundary are exactly what a human needs to eyeball,
not something a keyword check can grade. A few loose sanity assertions
(relevance bounds, event_type membership) catch outright drift.

Usage:
    uv run python -m pulse.evals.topic_signal_extraction
        Runs every case against ANALYSIS_MODELS.
    uv run python -m pulse.evals.topic_signal_extraction <model-slug> [...]
        Runs every case against the given model(s) instead.
"""

from __future__ import annotations

import asyncio
import functools
import sys
from dataclasses import dataclass, field

from pulse.llm import complete_structured
from pulse.models import Source, SourceItem
from pulse.patterns.topic_signal import EventType, TopicSignal, analyze_items

ANALYSIS_MODELS = [
    "openrouter/qwen/qwen3.5-flash-02-23",
    "openrouter/google/gemini-2.5-flash-lite",
]
LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 700


@dataclass
class Case:
    name: str
    query: str
    item: SourceItem
    max_relevance: float | None = None  # off-topic item must score at or below
    min_relevance: float | None = None  # on-topic item must score at or above
    expected_event_types: list[EventType] = field(default_factory=list)  # empty = no check

    def run(self, model: str) -> tuple[TopicSignal | None, list[str]]:
        analyze_llm = functools.partial(
            complete_structured,
            models=[model],
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
        )
        result = asyncio.run(analyze_items(self.query, [self.item], analyze_llm))[0]
        if result.signal is None:
            return None, [f"analysis failed: {result.error}"]
        return result.signal, self._check(result.signal)

    def _check(self, signal: TopicSignal) -> list[str]:
        failures = []
        if self.max_relevance is not None and signal.relevance > self.max_relevance:
            failures.append(f"relevance={signal.relevance:.2f} > {self.max_relevance} (off-topic)")
        if self.min_relevance is not None and signal.relevance < self.min_relevance:
            failures.append(f"relevance={signal.relevance:.2f} < {self.min_relevance} (on-topic)")
        if self.expected_event_types and signal.event_type not in self.expected_event_types:
            allowed = [e.value for e in self.expected_event_types]
            failures.append(f"event_type={signal.event_type.value} not in {allowed}")
        return failures


CASES: list[Case] = [
    Case(
        name="1 new model release, on-topic",
        query="new AI model releases",
        item=SourceItem(
            title="Anthropic ships Claude Opus 4.8",
            url="https://a.example/opus-4-8",
            score=0.95,
            summary="Anthropic announced general availability of Claude Opus "
            "4.8 today, its newest flagship model, with improved reasoning "
            "and coding benchmarks.",
            source=Source.HACKER_NEWS,
            published_date="2026-07-20",
        ),
        min_relevance=0.6,
        expected_event_types=[EventType.RELEASE],
    ),
    Case(
        name="2 off-topic item",
        query="new AI model releases",
        item=SourceItem(
            title="Best cast iron skillet seasoning tips",
            url="https://a.example/skillet-tips",
            score=0.6,
            summary="A discussion thread on maintaining cast iron cookware: "
            "how to season, clean, and store it without rust.",
            source=Source.HACKER_NEWS,
            published_date="2026-07-10",
        ),
        max_relevance=0.3,
    ),
    Case(
        name="3 recap-worded item",
        query="API pricing changes",
        item=SourceItem(
            title="Reminder: our API price cut is now live",
            url="https://a.example/price-cut-recap",
            score=0.4,
            summary="As previously announced last month, our reduced API "
            "pricing has now taken effect for all customers.",
            source=Source.NEWSLETTER,
            published_date="2026-07-15",
        ),
        expected_event_types=[EventType.RECAP],
    ),
    Case(
        # No assertions — this one is purely for eyeballing how the model
        # handles a genuinely thin, near-content-free item.
        name="4 sparse item",
        query="software updates",
        item=SourceItem(
            title="update",
            url="https://a.example/sparse-update",
            score=0.3,
            summary="minor fixes",
            source=Source.YOUTUBE,
        ),
    ),
]


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args:
        models = [f"openrouter/{m.removeprefix('openrouter/')}" for m in args]
    else:
        models = ANALYSIS_MODELS

    exit_code = 0
    for model in models:
        print(f"\n=== {model} ===")
        passed = 0
        for case in CASES:
            try:
                signal, failures = case.run(model)
            except Exception as exc:  # provider errors count as case failure
                signal, failures = None, [f"error: {exc}"]
            passed += not failures
            status = "PASS" if not failures else "FAIL"
            print(f"[{status}] {case.name}")
            if signal is not None:
                print(
                    f"    topic={signal.topic!r} event_type={signal.event_type.value} "
                    f"relevance={signal.relevance:.2f} confidence={signal.confidence:.2f}"
                )
                print(f"    key_change={signal.key_change!r}")
                print(f"    evidence={signal.evidence!r}")
            for failure in failures:
                print(f"    -> {failure}")
        print(f"--- {model}: {passed}/{len(CASES)} passed")
        if passed != len(CASES):
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
