"""Deterministic tests for the research workflow core.

No network: the coordinator and analyzer are both injected. Most tests use
counting fakes returning canned results; one integration test drives the real
`run_sources` through in-process fake runners to prove aggregation flows through.
"""

from __future__ import annotations

import asyncio

import pytest

from pulse.llm import ProviderBillingError, ProviderConfigurationError
from pulse.models import Source, SourceItem, SourceItemList
from pulse.patterns.parallel import (
    ParallelRunResult,
    RunStatus,
    SourceOutput,
    SourceRunner,
    SourceRunResult,
    run_sources,
)
from pulse.patterns.topic_signal import (
    AnalysisRunStatus,
    AnalysisStatus,
    EventType,
    TopicSignal,
    TopicSignalResult,
)
from pulse.workflows.research import (
    Analyzer,
    Coordinator,
    InvalidQueryError,
    NodeName,
    PulseInput,
    build_research_graph,
)

OUTPUT_KEYS = {"result", "analysis"}


def _item(url: str, source: Source = Source.ARXIV) -> SourceItem:
    return SourceItem(title="t", url=url, score=0.9, summary="s", source=source)


def _signal() -> TopicSignal:
    return TopicSignal(
        topic="t",
        event_type=EventType.RELEASE,
        key_change="k",
        relevance=0.5,
        confidence=0.5,
        evidence="e",
    )


def _ok(item: SourceItem) -> TopicSignalResult:
    return TopicSignalResult(item=item, status=AnalysisStatus.SUCCESS, signal=_signal())


def _failed(item: SourceItem, error: str = "ModelsExhaustedError") -> TopicSignalResult:
    return TopicSignalResult(item=item, status=AnalysisStatus.FAILED, error=error)


class _CountingCoordinator:
    def __init__(self, result: ParallelRunResult) -> None:
        self._result = result
        self.calls: list[str] = []

    async def __call__(self, query: str) -> ParallelRunResult:
        self.calls.append(query)
        return self._result


class _CountingAnalyzer:
    """Records each call; by default reports every item analyzed."""

    def __init__(self, results: list[TopicSignalResult] | None = None) -> None:
        self._results = results
        self.calls: list[tuple[str, SourceItemList]] = []

    async def __call__(self, query: str, items: SourceItemList) -> list[TopicSignalResult]:
        self.calls.append((query, items))
        return self._results if self._results is not None else [_ok(item) for item in items]


class _RaisingAnalyzer:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.calls: list[str] = []

    async def __call__(self, query: str, items: SourceItemList) -> list[TopicSignalResult]:
        self.calls.append(query)
        raise self._exc


def _run(coordinator: Coordinator, query: str, analyzer: Analyzer | None = None) -> dict:
    graph = build_research_graph(coordinator, analyzer or _CountingAnalyzer())
    inp: PulseInput = {"query": query}
    return asyncio.run(graph.ainvoke(inp))


def _executed_nodes(
    coordinator: Coordinator, query: str = "agents", analyzer: Analyzer | None = None
) -> list[str]:
    graph = build_research_graph(coordinator, analyzer or _CountingAnalyzer())

    async def _collect() -> list[str]:
        seen: list[str] = []
        async for update in graph.astream({"query": query}, stream_mode="updates"):
            seen.extend(update.keys())
        return seen

    return asyncio.run(_collect())


def _success_result(items: SourceItemList) -> ParallelRunResult:
    results = [SourceRunResult(source=Source.ARXIV, items=items, status=RunStatus.SUCCESS)]
    return ParallelRunResult(results=results, items=items, status=RunStatus.SUCCESS)


def test_valid_query_reaches_coordinator_with_stripped_query() -> None:
    coordinator = _CountingCoordinator(_success_result([_item("https://a.example/1")]))

    _run(coordinator, "  agents  ")

    assert coordinator.calls == ["agents"]


def test_coordinator_called_exactly_once() -> None:
    coordinator = _CountingCoordinator(_success_result([]))

    _run(coordinator, "agents")

    assert len(coordinator.calls) == 1


@pytest.mark.parametrize("query", ["", "   ", "\t\n"])
def test_empty_query_raises_before_coordinator(query: str) -> None:
    coordinator = _CountingCoordinator(_success_result([]))
    analyzer = _CountingAnalyzer()

    with pytest.raises(InvalidQueryError):
        _run(coordinator, query, analyzer)

    assert coordinator.calls == []
    assert analyzer.calls == []


def test_success_routes_to_finalize_results_and_carries_items() -> None:
    items = [_item("https://a.example/1"), _item("https://a.example/2")]
    result = _success_result(items)

    output = _run(_CountingCoordinator(result), "agents")

    assert output["result"] is result
    assert output["result"].status is RunStatus.SUCCESS
    assert output["result"].items == items


def test_partial_routes_to_finalize_results_and_preserves_failed_source() -> None:
    items = [_item("https://a.example/1")]
    result = ParallelRunResult(
        results=[
            SourceRunResult(source=Source.HACKER_NEWS, items=items, status=RunStatus.SUCCESS),
            SourceRunResult(
                source=Source.ARXIV, items=[], status=RunStatus.FAILED, error="RuntimeError"
            ),
        ],
        items=items,
        status=RunStatus.PARTIAL,
    )

    output = _run(_CountingCoordinator(result), "agents")

    assert output["result"].status is RunStatus.PARTIAL
    assert output["result"].items == items
    failed = output["result"].results[1]
    assert failed.status is RunStatus.FAILED
    assert failed.error == "RuntimeError"


def test_failed_aggregate_routes_to_finalize_failure() -> None:
    result = ParallelRunResult(
        results=[SourceRunResult(source=Source.ARXIV, items=[], status=RunStatus.FAILED)],
        items=[],
        status=RunStatus.FAILED,
    )

    output = _run(_CountingCoordinator(result), "agents")

    assert output["result"].status is RunStatus.FAILED
    assert output["result"].items == []


@pytest.mark.parametrize(
    ("status", "expected", "forbidden"),
    [
        (RunStatus.SUCCESS, NodeName.FINALIZE_RESULTS, NodeName.FINALIZE_FAILURE),
        (RunStatus.PARTIAL, NodeName.FINALIZE_RESULTS, NodeName.FINALIZE_FAILURE),
        (RunStatus.FAILED, NodeName.FINALIZE_FAILURE, NodeName.FINALIZE_RESULTS),
    ],
)
def test_status_reaches_expected_terminal_node(
    status: RunStatus, expected: NodeName, forbidden: NodeName
) -> None:
    # Both terminals return the same shape, so routing must be asserted on the
    # executed node, not the output payload.
    result = ParallelRunResult(results=[], items=[], status=status)

    nodes = _executed_nodes(_CountingCoordinator(result))

    assert expected in nodes
    assert forbidden not in nodes


@pytest.mark.parametrize(
    ("status", "analyzes"),
    [(RunStatus.SUCCESS, True), (RunStatus.PARTIAL, True), (RunStatus.FAILED, False)],
)
def test_analysis_stage_runs_only_when_collection_did_not_fail(
    status: RunStatus, analyzes: bool
) -> None:
    result = ParallelRunResult(results=[], items=[], status=status)

    nodes = _executed_nodes(_CountingCoordinator(result))

    assert (NodeName.ANALYZE_ITEMS in nodes) is analyzes


def test_analyzer_called_exactly_once_with_the_collected_items() -> None:
    items = [_item("https://a.example/1"), _item("https://a.example/2")]
    analyzer = _CountingAnalyzer()

    output = _run(_CountingCoordinator(_success_result(items)), "  agents  ", analyzer)

    assert len(analyzer.calls) == 1
    query, seen = analyzer.calls[0]
    assert query == "agents"
    assert seen is output["result"].items
    assert [i.url for i in seen] == [i.url for i in items]


def test_total_collection_failure_skips_analysis() -> None:
    result = ParallelRunResult(results=[], items=[], status=RunStatus.FAILED)
    analyzer = _CountingAnalyzer()

    output = _run(_CountingCoordinator(result), "agents", analyzer)

    assert analyzer.calls == []
    assert output["analysis"].status is AnalysisRunStatus.SKIPPED
    assert output["analysis"].results is None
    assert output["analysis"].analyzed_count == 0
    assert output["analysis"].failed_count == 0
    assert output["analysis"].error is None


def test_partial_collection_analyzes_the_surviving_items() -> None:
    items = [_item("https://a.example/1")]
    result = ParallelRunResult(
        results=[
            SourceRunResult(source=Source.HACKER_NEWS, items=items, status=RunStatus.SUCCESS),
            SourceRunResult(
                source=Source.ARXIV, items=[], status=RunStatus.FAILED, error="RuntimeError"
            ),
        ],
        items=items,
        status=RunStatus.PARTIAL,
    )
    analyzer = _CountingAnalyzer()

    output = _run(_CountingCoordinator(result), "agents", analyzer)

    assert [i.url for i in analyzer.calls[0][1]] == ["https://a.example/1"]
    assert output["result"].status is RunStatus.PARTIAL
    assert output["analysis"].status is AnalysisRunStatus.SUCCESS
    assert output["analysis"].analyzed_count == 1


def test_zero_collected_items_is_a_successful_analysis() -> None:
    output = _run(_CountingCoordinator(_success_result([])), "agents")

    assert output["analysis"].results == []
    assert output["analysis"].status is AnalysisRunStatus.SUCCESS
    assert output["analysis"].analyzed_count == 0
    assert output["analysis"].failed_count == 0


def test_one_item_failure_preserves_every_item_and_the_successful_analyses() -> None:
    items = [_item(f"https://a.example/{n}") for n in (1, 2, 3)]
    analyzer = _CountingAnalyzer([_ok(items[0]), _failed(items[1]), _ok(items[2])])

    output = _run(_CountingCoordinator(_success_result(items)), "agents", analyzer)

    assert [r.item for r in output["analysis"].results] == items
    assert output["analysis"].status is AnalysisRunStatus.PARTIAL
    assert output["analysis"].analyzed_count == 2
    assert output["analysis"].failed_count == 1
    assert output["analysis"].results[1].error == "ModelsExhaustedError"
    assert [r.signal for r in output["analysis"].results][0] is not None


def test_every_item_failing_is_an_analysis_failure_not_a_collection_failure() -> None:
    items = [_item("https://a.example/1"), _item("https://a.example/2")]
    analyzer = _CountingAnalyzer([_failed(item) for item in items])

    output = _run(_CountingCoordinator(_success_result(items)), "agents", analyzer)

    assert output["result"].status is RunStatus.SUCCESS
    assert output["analysis"].status is AnalysisRunStatus.FAILED
    assert output["analysis"].analyzed_count == 0
    assert output["analysis"].failed_count == 2
    # Independent failures still expose a full per-item result set.
    assert len(output["analysis"].results) == 2
    assert output["analysis"].error is None


@pytest.mark.parametrize(
    "exc",
    [ProviderConfigurationError("no key"), ProviderBillingError("payment required")],
)
def test_shared_provider_failure_exposes_one_run_level_error_and_keeps_items(
    exc: Exception,
) -> None:
    items = [_item("https://a.example/1"), _item("https://a.example/2")]

    output = _run(_CountingCoordinator(_success_result(items)), "agents", _RaisingAnalyzer(exc))

    assert output["result"].items == items
    assert output["analysis"].results is None
    assert output["analysis"].status is AnalysisRunStatus.FAILED
    assert output["analysis"].analyzed_count == 0
    assert output["analysis"].failed_count == 0
    assert output["analysis"].error == type(exc).__name__


def test_shared_failure_error_carries_no_exception_message() -> None:
    output = _run(
        _CountingCoordinator(_success_result([_item("https://a.example/1")])),
        "agents",
        _RaisingAnalyzer(ProviderConfigurationError("OPENROUTER_API_KEY not set — check .env")),
    )

    assert output["analysis"].error == "ProviderConfigurationError"
    assert "OPENROUTER_API_KEY" not in output["analysis"].error


def test_analysis_order_matches_item_order() -> None:
    items = [_item(f"https://a.example/{n}") for n in range(5)]

    output = _run(_CountingCoordinator(_success_result(items)), "agents")

    assert [r.item.url for r in output["analysis"].results] == [i.url for i in items]


def test_repeated_runs_are_deterministic() -> None:
    items = [
        _item("https://a.example/1", source=Source.HACKER_NEWS),
        _item("https://b.example/2", source=Source.ARXIV),
    ]

    def make_result() -> ParallelRunResult:
        # A fresh but content-equal result each call, as two independent runs
        # of the coordinator would produce.
        return ParallelRunResult(
            results=[
                SourceRunResult(
                    source=Source.HACKER_NEWS, items=items[:1], status=RunStatus.SUCCESS
                ),
                SourceRunResult(
                    source=Source.ARXIV,
                    items=items[1:],
                    status=RunStatus.PARTIAL,
                    error="no_results",
                ),
            ],
            items=items,
            status=RunStatus.PARTIAL,
        )

    async def coordinator(query: str) -> ParallelRunResult:
        return make_result()

    graph = build_research_graph(coordinator, _CountingAnalyzer())
    first = asyncio.run(graph.ainvoke({"query": "agents"}))
    second = asyncio.run(graph.ainvoke({"query": "agents"}))

    # Same public output shape.
    assert set(first.keys()) == set(second.keys()) == OUTPUT_KEYS
    # Same order of per-source results and of combined items.
    assert [r.source for r in first["result"].results] == [
        r.source for r in second["result"].results
    ]
    assert [i.url for i in first["result"].items] == [i.url for i in second["result"].items]
    # Same executed path, hence the same terminal branch.
    assert _executed_nodes(coordinator) == _executed_nodes(coordinator)


def test_public_output_exposes_only_the_documented_keys() -> None:
    output = _run(_CountingCoordinator(_success_result([])), "agents")

    assert set(output.keys()) == OUTPUT_KEYS


def test_integration_real_coordinator_over_fake_runners_yields_partial() -> None:
    items = [_item("https://a.example/1", source=Source.HACKER_NEWS)]

    def ok(query: str) -> SourceOutput:
        return SourceOutput(items=items, status=RunStatus.SUCCESS)

    def failing(query: str) -> SourceOutput:
        raise ValueError("boom")

    runners = [
        SourceRunner(source=Source.HACKER_NEWS, run=ok),
        SourceRunner(source=Source.ARXIV, run=failing),
    ]

    async def coordinator(query: str) -> ParallelRunResult:
        return await run_sources(query, runners)

    graph = build_research_graph(coordinator, _CountingAnalyzer())
    output = asyncio.run(graph.ainvoke({"query": "agents"}))

    assert output["result"].status is RunStatus.PARTIAL
    assert output["result"].items == items
    assert output["result"].results[1].status is RunStatus.FAILED


def test_unexpected_coordinator_error_is_not_swallowed() -> None:
    async def coordinator(query: str) -> ParallelRunResult:
        raise RuntimeError("boom")

    graph = build_research_graph(coordinator, _CountingAnalyzer())
    with pytest.raises(RuntimeError):
        asyncio.run(graph.ainvoke({"query": "agents"}))


def test_unexpected_analyzer_error_is_not_swallowed() -> None:
    coordinator = _CountingCoordinator(_success_result([_item("https://a.example/1")]))

    graph = build_research_graph(coordinator, _RaisingAnalyzer(RuntimeError("bug")))
    with pytest.raises(RuntimeError):
        asyncio.run(graph.ainvoke({"query": "agents"}))


def test_cancellation_propagates() -> None:
    started = asyncio.Event()

    async def coordinator(query: str) -> ParallelRunResult:
        started.set()
        await asyncio.sleep(10)  # interrupted by the cancel below, never elapses
        return _success_result([])

    async def main() -> None:
        graph = build_research_graph(coordinator, _CountingAnalyzer())
        task = asyncio.create_task(graph.ainvoke({"query": "agents"}))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())


def test_analyzer_cancellation_propagates() -> None:
    started = asyncio.Event()
    coordinator = _CountingCoordinator(_success_result([_item("https://a.example/1")]))

    async def analyzer(query: str, items: SourceItemList) -> list[TopicSignalResult]:
        started.set()
        await asyncio.sleep(10)  # interrupted by the cancel below, never elapses
        return []

    async def main() -> None:
        graph = build_research_graph(coordinator, analyzer)
        task = asyncio.create_task(graph.ainvoke({"query": "agents"}))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
