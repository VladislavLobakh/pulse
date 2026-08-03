"""Research workflow — the deterministic core that wraps the parallel coordinator.

The graph owns only state, stage ordering, and status routing: validate the
query, call the injected coordinator exactly once, analyze the items it returns
exactly once, then route on status to a terminal node. Everything the
coordinator already owns (concurrency, failure isolation, timing, ordering,
aggregation, URL dedup) stays in `patterns.parallel`, and per-item extraction
stays in `patterns.topic_signal`; this module never fetches, aggregates, or
analyzes itself.

Collection and analysis statuses stay independent: a fully failed collection
skips analysis (`SKIPPED`), and a failed analysis leaves the collection result
untouched. The graph is acyclic, so it carries no `recursion_limit` guard
(unlike the looping ReAct engine). `PulseInput`/`PulseState`/`PulseOutput` are
wired as the graph's separate input/state/output schemas so internal fields
never leak into the public result.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import NotRequired, TypedDict

from langgraph.graph import END, StateGraph

from pulse.llm import FAIL_FAST_ERRORS
from pulse.models import SourceItemList
from pulse.patterns.parallel import ParallelRunResult, RunStatus
from pulse.patterns.topic_signal import AnalysisRunResult, TopicSignalResult

# (query) -> aggregate result. Injected so the graph never builds real sources.
Coordinator = Callable[[str], Awaitable[ParallelRunResult]]

# (query, items) -> one result per item. Injected so the graph never binds a
# model chain or reaches the provider itself.
Analyzer = Callable[[str, SourceItemList], Awaitable[list[TopicSignalResult]]]


class InvalidQueryError(ValueError):
    """Empty/whitespace query — raised before the coordinator runs."""


class PulseInput(TypedDict):
    query: str


class PulseState(TypedDict):
    query: str
    parallel_result: NotRequired[ParallelRunResult]
    result: NotRequired[ParallelRunResult]
    analysis: NotRequired[AnalysisRunResult]


class PulseOutput(TypedDict):
    result: ParallelRunResult
    analysis: AnalysisRunResult


class NodeName(StrEnum):
    INITIALIZE = "initialize_state"
    COLLECT_SOURCES = "collect_sources"
    ANALYZE_ITEMS = "analyze_items"
    FINALIZE_RESULTS = "finalize_results"
    FINALIZE_FAILURE = "finalize_failure"


def _initialize_state(state: PulseState) -> dict:
    query = state["query"].strip()
    # Reject before the coordinator runs; an empty query is a validation error,
    # not a FAILED run (which means sources actually ran and failed).
    if not query:
        raise InvalidQueryError("empty query")
    return {"query": query}


def _make_collect_sources(coordinator: Coordinator) -> Callable[[PulseState], Awaitable[dict]]:
    async def _collect_sources(state: PulseState) -> dict:
        # No try/except: the coordinator isolates per-source failures itself, so
        # anything raised here (cancellation, misconfiguration) must propagate.
        parallel_result = await coordinator(state["query"])
        return {"parallel_result": parallel_result}

    return _collect_sources


def _make_analyze_items(analyzer: Analyzer) -> Callable[[PulseState], Awaitable[dict]]:
    async def _analyze_items(state: PulseState) -> dict:
        items = state["parallel_result"].items
        try:
            results = await analyzer(state["query"], items)
        except FAIL_FAST_ERRORS as exc:
            return {"analysis": AnalysisRunResult.aborted(type(exc).__name__)}
        return {"analysis": AnalysisRunResult.completed(results)}

    return _analyze_items


def _route_by_status(state: PulseState) -> NodeName:
    if state["parallel_result"].status is RunStatus.FAILED:
        return NodeName.FINALIZE_FAILURE
    return NodeName.ANALYZE_ITEMS


def _finalize_results(state: PulseState) -> dict:
    return {"result": state["parallel_result"], "analysis": state["analysis"]}


def _finalize_failure(state: PulseState) -> dict:
    return {"result": state["parallel_result"], "analysis": AnalysisRunResult.skipped()}


def build_research_graph(coordinator: Coordinator, analyzer: Analyzer):
    """Compile the research workflow once; invoke the result via `ainvoke`."""
    graph = StateGraph(PulseState, input_schema=PulseInput, output_schema=PulseOutput)
    graph.add_node(NodeName.INITIALIZE, _initialize_state)
    graph.add_node(NodeName.COLLECT_SOURCES, _make_collect_sources(coordinator))
    graph.add_node(NodeName.ANALYZE_ITEMS, _make_analyze_items(analyzer))
    graph.add_node(NodeName.FINALIZE_RESULTS, _finalize_results)
    graph.add_node(NodeName.FINALIZE_FAILURE, _finalize_failure)

    graph.set_entry_point(NodeName.INITIALIZE)
    graph.add_edge(NodeName.INITIALIZE, NodeName.COLLECT_SOURCES)
    graph.add_conditional_edges(
        NodeName.COLLECT_SOURCES,
        _route_by_status,
        {
            NodeName.ANALYZE_ITEMS: NodeName.ANALYZE_ITEMS,
            NodeName.FINALIZE_FAILURE: NodeName.FINALIZE_FAILURE,
        },
    )
    graph.add_edge(NodeName.ANALYZE_ITEMS, NodeName.FINALIZE_RESULTS)
    graph.add_edge(NodeName.FINALIZE_RESULTS, END)
    graph.add_edge(NodeName.FINALIZE_FAILURE, END)

    return graph.compile()
