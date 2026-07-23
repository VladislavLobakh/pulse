"""Deterministic tests for the research workflow core.

No network: the coordinator is injected. Most tests use a counting fake that
returns a canned `ParallelRunResult`; one integration test drives the real
`run_sources` through in-process fake runners to prove aggregation flows through.
"""

from __future__ import annotations

import asyncio

import pytest

from pulse.models import Source, SourceItem, SourceItemList
from pulse.patterns.parallel import (
    ParallelRunResult,
    RunStatus,
    SourceOutput,
    SourceRunner,
    SourceRunResult,
    run_sources,
)
from pulse.workflows.research import (
    Coordinator,
    NodeName,
    PulseInput,
    build_research_graph,
)


def _item(url: str, source: Source = Source.ARXIV) -> SourceItem:
    return SourceItem(title="t", url=url, score=0.9, summary="s", source=source)


class _CountingCoordinator:
    def __init__(self, result: ParallelRunResult) -> None:
        self._result = result
        self.calls: list[str] = []

    async def __call__(self, query: str) -> ParallelRunResult:
        self.calls.append(query)
        return self._result


def _run(coordinator: Coordinator, query: str) -> dict:
    graph = build_research_graph(coordinator)
    inp: PulseInput = {"query": query}
    return asyncio.run(graph.ainvoke(inp))


def _executed_nodes(coordinator: Coordinator, query: str = "agents") -> list[str]:
    graph = build_research_graph(coordinator)

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

    with pytest.raises(ValueError):
        _run(coordinator, query)

    assert coordinator.calls == []


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


def test_public_output_exposes_only_result() -> None:
    output = _run(_CountingCoordinator(_success_result([])), "agents")

    assert set(output.keys()) == {"result"}


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

    graph = build_research_graph(coordinator)
    output = asyncio.run(graph.ainvoke({"query": "agents"}))

    assert output["result"].status is RunStatus.PARTIAL
    assert output["result"].items == items
    assert output["result"].results[1].status is RunStatus.FAILED


def test_unexpected_coordinator_error_is_not_swallowed() -> None:
    async def coordinator(query: str) -> ParallelRunResult:
        raise RuntimeError("boom")

    graph = build_research_graph(coordinator)
    with pytest.raises(RuntimeError):
        asyncio.run(graph.ainvoke({"query": "agents"}))


def test_cancellation_propagates() -> None:
    started = asyncio.Event()

    async def coordinator(query: str) -> ParallelRunResult:
        started.set()
        await asyncio.sleep(10)  # interrupted by the cancel below, never elapses
        return _success_result([])

    async def main() -> None:
        graph = build_research_graph(coordinator)
        task = asyncio.create_task(graph.ainvoke({"query": "agents"}))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
