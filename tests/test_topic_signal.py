"""Deterministic, network-free tests for the topic_signal analyzer engine.

These are plumbing tests: they prove analyze_items wires inputs, outputs, and
errors correctly, not that any particular extraction is "correct" (that's a
live-model eval concern, out of scope here — see test_topic_signal_golden.py
for the reviewed fixture cases and their scope note).
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from pydantic import ValidationError

from pulse import llm as llm_module
from pulse.models import Source, SourceItem
from pulse.patterns.topic_signal import (
    AnalysisRunResult,
    AnalysisRunStatus,
    AnalysisStatus,
    EventType,
    TopicSignal,
    TopicSignalResult,
    analyze_items,
)

WAIT_TIMEOUT = 5.0


def _item(url: str, title: str = "t", summary: str = "s") -> SourceItem:
    return SourceItem(title=title, url=url, score=0.9, summary=summary, source=Source.ARXIV)


def _signal(
    topic: str = "t",
    event_type: EventType = EventType.OTHER,
    key_change: str = "k",
    relevance: float = 0.8,
    confidence: float = 0.8,
    evidence: str = "e",
) -> TopicSignal:
    return TopicSignal(
        topic=topic,
        event_type=event_type,
        key_change=key_change,
        relevance=relevance,
        confidence=confidence,
        evidence=evidence,
    )


def _url_from_messages(messages: list[dict]) -> str:
    for line in messages[1]["content"].splitlines():
        if line.startswith("URL: "):
            return line.removeprefix("URL: ")
    raise AssertionError("no URL line found in messages")


# --- Pydantic validation ---


def test_topic_signal_accepts_every_event_type() -> None:
    for event_type in EventType:
        signal = _signal(event_type=event_type)
        assert signal.event_type is event_type


@pytest.mark.parametrize(
    "field,value",
    [("relevance", 1.5), ("relevance", -0.1), ("confidence", 1.5), ("confidence", -0.1)],
)
def test_topic_signal_rejects_out_of_range_floats(field: str, value: float) -> None:
    kwargs = dict(
        topic="t",
        event_type=EventType.OTHER,
        key_change="k",
        relevance=0.5,
        confidence=0.5,
        evidence="e",
    )
    kwargs[field] = value
    with pytest.raises(ValidationError):
        TopicSignal(**kwargs)


@pytest.mark.parametrize("field", ["topic", "key_change", "evidence"])
@pytest.mark.parametrize("blank", ["", "   "])
def test_topic_signal_rejects_blank_strings(field: str, blank: str) -> None:
    kwargs = dict(
        topic="t",
        event_type=EventType.OTHER,
        key_change="k",
        relevance=0.5,
        confidence=0.5,
        evidence="e",
    )
    kwargs[field] = blank
    with pytest.raises(ValidationError):
        TopicSignal(**kwargs)


def test_topic_signal_rejects_invalid_event_type() -> None:
    with pytest.raises(ValidationError):
        TopicSignal(
            topic="t",
            event_type="not-a-real-type",
            key_change="k",
            relevance=0.5,
            confidence=0.5,
            evidence="e",
        )


# --- UNKNOWN event_type plumbing ---


def test_unknown_event_type_round_trips_through_analyzer() -> None:
    signal = _signal(event_type=EventType.UNKNOWN)

    def fake(*, messages: list[dict], response_model: type[TopicSignal]) -> TopicSignal:
        return signal

    results = asyncio.run(analyze_items("q", [_item("https://a.example/1")], fake))

    assert results[0].signal is signal
    assert results[0].signal.event_type is EventType.UNKNOWN


# --- Bounded concurrency ---


def test_bounded_concurrency_never_exceeds_limit() -> None:
    # A Barrier(N) alone doesn't prove a bound — unlimited concurrency would
    # still self-organize into groups of N. Track peak concurrency instead.
    max_concurrency = 2
    lock = threading.Lock()
    active = 0
    peak = 0

    def fake(*, messages: list[dict], response_model: type[TopicSignal]) -> TopicSignal:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return _signal()

    items = [_item(f"https://a.example/{i}") for i in range(6)]
    results = asyncio.run(analyze_items("q", items, fake, max_concurrency=max_concurrency))

    assert peak == max_concurrency
    assert all(r.status is AnalysisStatus.SUCCESS for r in results)


@pytest.mark.parametrize("bad_value", [0, -1])
def test_max_concurrency_below_one_raises_value_error(bad_value: int) -> None:
    def fake(*, messages: list[dict], response_model: type[TopicSignal]) -> TopicSignal:
        raise AssertionError("must not be called")

    with pytest.raises(ValueError):
        asyncio.run(
            analyze_items("q", [_item("https://a.example/1")], fake, max_concurrency=bad_value)
        )


# --- At-most-once ---


def test_analyzes_every_item_exactly_once() -> None:
    calls: dict[str, int] = {}
    lock = threading.Lock()

    def fake(*, messages: list[dict], response_model: type[TopicSignal]) -> TopicSignal:
        url = _url_from_messages(messages)
        with lock:
            calls[url] = calls.get(url, 0) + 1
        return _signal()

    items = [_item(f"https://a.example/{i}") for i in range(5)]
    asyncio.run(analyze_items("q", items, fake))

    assert calls == {item.url: 1 for item in items}


# --- Deterministic ordering ---


def test_ordering_preserved_when_completion_order_reversed() -> None:
    first_done = threading.Event()
    item_a = _item("https://example.com/a")
    item_b = _item("https://example.com/b")

    def fake(*, messages: list[dict], response_model: type[TopicSignal]) -> TopicSignal:
        url = _url_from_messages(messages)
        if url == item_a.url:
            # Blocks until B has finished, so B provably completes first.
            assert first_done.wait(timeout=WAIT_TIMEOUT)
            return _signal(topic="a")
        signal = _signal(topic="b")
        first_done.set()
        return signal

    results = asyncio.run(analyze_items("q", [item_a, item_b], fake))

    assert [r.item.url for r in results] == [item_a.url, item_b.url]
    assert results[0].signal.topic == "a"
    assert results[1].signal.topic == "b"


# --- Per-item failure isolation ---


def test_one_item_models_exhausted_isolated_others_succeed() -> None:
    good_item = _item("https://a.example/1")
    bad_item = _item("https://a.example/2")

    def fake(*, messages: list[dict], response_model: type[TopicSignal]) -> TopicSignal:
        if _url_from_messages(messages) == bad_item.url:
            raise llm_module.ModelsExhaustedError("All configured models exhausted: [...]")
        return _signal()

    results = asyncio.run(analyze_items("q", [good_item, bad_item], fake))

    good, bad = results
    assert good.status is AnalysisStatus.SUCCESS
    assert good.signal is not None
    assert bad.status is AnalysisStatus.FAILED
    assert bad.error == "ModelsExhaustedError"
    assert bad.signal is None


# --- Shared-error fail-fast ---


@pytest.mark.parametrize(
    "exc_cls", [llm_module.ProviderBillingError, llm_module.ProviderConfigurationError]
)
def test_shared_errors_fail_fast(exc_cls: type[Exception]) -> None:
    def fake(*, messages: list[dict], response_model: type[TopicSignal]) -> TopicSignal:
        raise exc_cls("boom")

    with pytest.raises(exc_cls):
        asyncio.run(analyze_items("q", [_item("https://a.example/1")], fake))


@pytest.mark.parametrize(
    "exc", [llm_module.ProviderConfigurationError("boom"), RuntimeError("boom")]
)
def test_any_propagating_error_stops_queued_items_from_starting(exc: Exception) -> None:
    """except BaseException in _analyze_one is one code path for every
    propagating error — a fail-fast class and a bare RuntimeError must both
    stop items still queued behind the semaphore, not just the named
    fail-fast classes (asyncio.gather does not cancel siblings on its own)."""
    calls: list[str] = []
    lock = threading.Lock()
    failing_item = _item("https://a.example/1")
    queued_items = [_item(f"https://a.example/{i}") for i in range(2, 6)]

    def fake(*, messages: list[dict], response_model: type[TopicSignal]) -> TopicSignal:
        url = _url_from_messages(messages)
        with lock:
            calls.append(url)
        if url == failing_item.url:
            raise exc
        return _signal()

    with pytest.raises(type(exc)):
        asyncio.run(analyze_items("q", [failing_item, *queued_items], fake, max_concurrency=1))

    assert calls == [failing_item.url]


@pytest.mark.parametrize("exc", [RuntimeError("boom"), TypeError("bug")])
def test_unclassified_error_propagates_not_isolated(exc: Exception) -> None:
    """Only ModelsExhaustedError is isolated per-item; anything else — an
    unclassified RuntimeError or a real bug — must propagate and abort the
    batch instead, via the same except BaseException path."""

    def fake(*, messages: list[dict], response_model: type[TopicSignal]) -> TopicSignal:
        raise exc

    with pytest.raises(type(exc)):
        asyncio.run(analyze_items("q", [_item("https://a.example/1")], fake))


# --- Cancellation propagation ---


def test_cancellation_propagates_and_is_not_swallowed() -> None:
    started = threading.Event()
    release = threading.Event()

    def blocking(*, messages: list[dict], response_model: type[TopicSignal]) -> TopicSignal:
        started.set()
        release.wait(timeout=WAIT_TIMEOUT)
        return _signal()

    async def main() -> None:
        task = asyncio.create_task(analyze_items("q", [_item("https://a.example/1")], blocking))
        await asyncio.to_thread(started.wait, WAIT_TIMEOUT)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(main())
    finally:
        # The worker thread cannot be interrupted; unblock it so pytest exits.
        release.set()


# --- Run-status aggregation ---


def _result(status: AnalysisStatus) -> TopicSignalResult:
    return TopicSignalResult(item=_item("https://a.example/1"), status=status)


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], AnalysisRunStatus.SUCCESS),
        ([AnalysisStatus.SUCCESS], AnalysisRunStatus.SUCCESS),
        ([AnalysisStatus.SUCCESS, AnalysisStatus.SUCCESS], AnalysisRunStatus.SUCCESS),
        ([AnalysisStatus.FAILED], AnalysisRunStatus.FAILED),
        ([AnalysisStatus.FAILED, AnalysisStatus.FAILED], AnalysisRunStatus.FAILED),
        ([AnalysisStatus.SUCCESS, AnalysisStatus.FAILED], AnalysisRunStatus.PARTIAL),
    ],
)
def test_completed_run_aggregates_item_statuses(
    statuses: list[AnalysisStatus], expected: AnalysisRunStatus
) -> None:
    run = AnalysisRunResult.completed([_result(s) for s in statuses])

    assert run.status is expected
    assert run.analyzed_count == statuses.count(AnalysisStatus.SUCCESS)
    assert run.failed_count == statuses.count(AnalysisStatus.FAILED)
    assert run.error is None


def test_completed_run_never_reports_skipped() -> None:
    """SKIPPED means the analyzer was never called, so no result set can imply it."""
    for statuses in ([], [AnalysisStatus.SUCCESS], [AnalysisStatus.FAILED]):
        run = AnalysisRunResult.completed([_result(s) for s in statuses])
        assert run.status is not AnalysisRunStatus.SKIPPED


def test_aborted_run_exposes_the_error_and_no_per_item_results() -> None:
    run = AnalysisRunResult.aborted("ProviderConfigurationError")

    assert run.results is None
    assert run.status is AnalysisRunStatus.FAILED
    assert run.error == "ProviderConfigurationError"
    assert run.analyzed_count == 0
    assert run.failed_count == 0


def test_skipped_run_is_not_a_failed_run() -> None:
    run = AnalysisRunResult.skipped()

    assert run.results is None
    assert run.status is AnalysisRunStatus.SKIPPED
    assert run.error is None
