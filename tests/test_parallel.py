"""Deterministic tests for the parallel fan-out engine.

Concurrency is mostly proven with threading primitives whose timeouts are
failure guards, not pacing. Two timing tests below use real sleeps by
necessity — they assert relative comparisons (slowest vs. sum, parallel vs.
measured sequential), never absolute wall-clock thresholds, so they stay
robust to scheduler jitter.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from pulse.models import Source, SourceItem, SourceItemList
from pulse.patterns.parallel import (
    ParallelRunResult,
    RunStatus,
    SourceOutput,
    SourceRunFn,
    SourceRunner,
    normalize_url,
    run_sources,
)

WAIT_TIMEOUT = 5.0


def _item(url: str, title: str = "t", source: Source = Source.ARXIV) -> SourceItem:
    return SourceItem(title=title, url=url, score=0.9, summary="s", source=source)


def _ok(items: SourceItemList) -> SourceOutput:
    return SourceOutput(items=items, status=RunStatus.SUCCESS)


def _runner(source: Source, fn: SourceRunFn) -> SourceRunner:
    return SourceRunner(source=source, run=fn)


def _run(runners: list[SourceRunner]) -> ParallelRunResult:
    return asyncio.run(run_sources("query", runners))


def test_runners_execute_concurrently_not_serially() -> None:
    # The barrier releases only when all three runners are in flight at once;
    # serialized execution breaks it, failing the runners and this assert.
    barrier = threading.Barrier(3)

    def make_run(url: str) -> SourceRunFn:
        def run(query: str) -> SourceOutput:
            barrier.wait(timeout=WAIT_TIMEOUT)
            return _ok([_item(url)])

        return run

    result = _run(
        [
            _runner(Source.HACKER_NEWS, make_run("https://a.example/1")),
            _runner(Source.ARXIV, make_run("https://a.example/2")),
            _runner(Source.YOUTUBE, make_run("https://a.example/3")),
        ]
    )

    assert result.status is RunStatus.SUCCESS
    assert len(result.items) == 3


def test_combines_items_from_multiple_successful_sources() -> None:
    a_items = [_item("https://a.example/1"), _item("https://a.example/2")]
    b_items = [_item("https://b.example/1")]

    result = _run(
        [
            _runner(Source.HACKER_NEWS, lambda query: _ok(a_items)),
            _runner(Source.ARXIV, lambda query: _ok(b_items)),
        ]
    )

    assert result.items == a_items + b_items
    assert [r.status for r in result.results] == [RunStatus.SUCCESS, RunStatus.SUCCESS]


def test_one_failure_keeps_other_results_and_yields_partial() -> None:
    items = [_item("https://a.example/1")]

    def failing(query: str) -> SourceOutput:
        raise ValueError("boom")

    result = _run(
        [
            _runner(Source.HACKER_NEWS, lambda query: _ok(items)),
            _runner(Source.ARXIV, failing),
        ]
    )

    assert result.status is RunStatus.PARTIAL
    assert result.items == items
    failed = result.results[1]
    assert failed.status is RunStatus.FAILED
    assert failed.error == "ValueError"
    assert failed.items == []


def test_all_failures_yield_failed_aggregate_without_raising() -> None:
    def failing(query: str) -> SourceOutput:
        raise RuntimeError("boom")

    result = _run([_runner(Source.HACKER_NEWS, failing), _runner(Source.ARXIV, failing)])

    assert result.status is RunStatus.FAILED
    assert result.items == []
    assert all(r.status is RunStatus.FAILED for r in result.results)


def test_error_is_class_name_and_never_leaks_detail() -> None:
    secret = "sk-secret-123"

    def failing(query: str) -> SourceOutput:
        raise RuntimeError(f"auth failed for key {secret} prompt=system...")

    result = _run([_runner(Source.HACKER_NEWS, failing)])

    assert result.results[0].error == "RuntimeError"
    assert secret not in repr(result)


def test_partial_source_output_is_preserved_and_items_included() -> None:
    items = [_item("https://a.example/1")]
    output = SourceOutput(items=items, status=RunStatus.PARTIAL, error="below_min_articles")

    result = _run([_runner(Source.HACKER_NEWS, lambda query: output)])

    assert result.results[0].status is RunStatus.PARTIAL
    assert result.results[0].error == "below_min_articles"
    assert result.items == items
    assert result.status is RunStatus.PARTIAL


def test_zero_items_with_success_passes_through_as_empty_success() -> None:
    result = _run([_runner(Source.HACKER_NEWS, lambda query: _ok([]))])

    assert result.results[0].status is RunStatus.SUCCESS
    assert result.status is RunStatus.SUCCESS
    assert result.items == []


def test_status_and_elapsed_populated_on_success_and_failure() -> None:
    def failing(query: str) -> SourceOutput:
        raise RuntimeError("boom")

    result = _run(
        [
            _runner(Source.HACKER_NEWS, lambda query: _ok([_item("https://a.example/1")])),
            _runner(Source.ARXIV, failing),
        ]
    )

    for source_result in result.results:
        assert isinstance(source_result.status, RunStatus)
        assert source_result.elapsed_ms >= 0
    assert isinstance(result.status, RunStatus)
    assert result.elapsed_ms >= 0


def test_duplicate_normalized_urls_first_runner_wins() -> None:
    first = _item("https://Example.com/a/", title="first")
    second = _item("https://example.com/a#frag", title="second")

    result = _run(
        [
            _runner(Source.HACKER_NEWS, lambda query: _ok([first])),
            _runner(Source.ARXIV, lambda query: _ok([second])),
        ]
    )

    assert result.items == [first]


def test_empty_urls_are_never_deduplicated() -> None:
    items = [_item("", title="one"), _item("", title="two")]

    result = _run([_runner(Source.HACKER_NEWS, lambda query: _ok(items))])

    assert result.items == items


def test_ordering_and_dedup_stable_when_completion_order_varies() -> None:
    b_done = threading.Event()
    a_item = _item("https://example.com/a", title="a")
    b_item = _item("https://example.com/a/", title="b")

    def run_a(query: str) -> SourceOutput:
        # Blocks until B has finished, so B provably completes first.
        assert b_done.wait(timeout=WAIT_TIMEOUT)
        return _ok([a_item])

    def run_b(query: str) -> SourceOutput:
        output = _ok([b_item])
        b_done.set()
        return output

    result = _run([_runner(Source.HACKER_NEWS, run_a), _runner(Source.ARXIV, run_b)])

    assert [r.source for r in result.results] == [Source.HACKER_NEWS, Source.ARXIV]
    assert result.items == [a_item]


def test_cancellation_propagates_and_is_not_swallowed() -> None:
    started = threading.Event()
    release = threading.Event()

    def blocking(query: str) -> SourceOutput:
        started.set()
        release.wait(timeout=WAIT_TIMEOUT)
        return _ok([])

    async def main() -> None:
        task = asyncio.create_task(run_sources("query", [_runner(Source.HACKER_NEWS, blocking)]))
        await asyncio.to_thread(started.wait, WAIT_TIMEOUT)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(main())
    finally:
        # The worker thread cannot be interrupted; unblock it so pytest exits.
        release.set()


def test_empty_runner_collection_raises_value_error() -> None:
    with pytest.raises(ValueError):
        asyncio.run(run_sources("query", []))


def test_normalize_url_rules() -> None:
    assert normalize_url(" HTTPS://Example.COM/Path/ ") == "https://example.com/Path"
    assert normalize_url("https://example.com/a#frag") == "https://example.com/a"
    assert normalize_url("https://example.com/a?b=C") == "https://example.com/a?b=C"
    assert normalize_url("") == ""


def test_normalize_url_malformed_input_falls_back_without_raising() -> None:
    assert normalize_url(" http://[bad ") == "http://[bad"

    item = _item("http://[bad")
    result = _run([_runner(Source.HACKER_NEWS, lambda query: _ok([item]))])
    assert result.items == [item]


def test_aggregate_elapsed_tracks_slowest_runner_not_the_sum() -> None:
    sleep_seconds = 0.2
    barrier = threading.Barrier(3)

    def run(query: str) -> SourceOutput:
        # All three must be in flight together before any sleeps, so the
        # sleeps provably overlap instead of racing to start first.
        barrier.wait(timeout=WAIT_TIMEOUT)
        time.sleep(sleep_seconds)
        return _ok([])

    result = _run(
        [
            _runner(Source.HACKER_NEWS, run),
            _runner(Source.ARXIV, run),
            _runner(Source.YOUTUBE, run),
        ]
    )

    per_source = [r.elapsed_ms for r in result.results]
    assert result.elapsed_ms >= max(per_source)
    assert result.elapsed_ms < sum(per_source)


def test_parallel_execution_is_faster_than_sequential_for_same_runners() -> None:
    sleep_seconds = 0.15

    def run(query: str) -> SourceOutput:
        time.sleep(sleep_seconds)
        return _ok([])

    runners = [
        _runner(Source.HACKER_NEWS, run),
        _runner(Source.ARXIV, run),
        _runner(Source.YOUTUBE, run),
    ]

    sequential_start = time.perf_counter()
    for runner in runners:
        runner.run("query")
    sequential_elapsed_ms = (time.perf_counter() - sequential_start) * 1000

    parallel_result = _run(runners)

    assert parallel_result.elapsed_ms < sequential_elapsed_ms
