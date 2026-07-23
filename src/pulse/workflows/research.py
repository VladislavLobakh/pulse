"""Research workflow — the deterministic core that wraps the parallel coordinator.

The graph owns only state, stage ordering, and status routing: validate the
query, call the injected coordinator exactly once, then route on its aggregate
status to a terminal node. Everything the coordinator already owns (concurrency,
failure isolation, timing, ordering, aggregation, URL dedup) stays in
`patterns.parallel`; this module never fetches or aggregates itself.

The graph is acyclic, so it carries no `recursion_limit` guard (unlike the
looping ReAct engine). `PulseInput`/`PulseState`/`PulseOutput` are wired as the
graph's separate input/state/output schemas so internal fields never leak into
the public result.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import NotRequired, TypedDict

from langgraph.graph import END, StateGraph

from pulse.logging_config import get_logger
from pulse.patterns.parallel import ParallelRunResult, RunStatus

logger = get_logger(__name__)

# (query) -> aggregate result. Injected so the graph never builds real sources.
Coordinator = Callable[[str], Awaitable[ParallelRunResult]]


class PulseInput(TypedDict):
    query: str


class PulseState(TypedDict):
    query: str
    parallel_result: NotRequired[ParallelRunResult]  # written by collect_sources
    result: NotRequired[ParallelRunResult]  # written by a terminal node


class PulseOutput(TypedDict):
    result: ParallelRunResult


class NodeName(StrEnum):
    INITIALIZE = "initialize_state"
    COLLECT_SOURCES = "collect_sources"
    FINALIZE_RESULTS = "finalize_results"
    FINALIZE_FAILURE = "finalize_failure"


def _initialize_state(state: PulseState) -> dict:
    query = state["query"].strip()
    # Reject before the coordinator runs; an empty query is a validation error,
    # not a FAILED run (which means sources actually ran and failed).
    if not query:
        raise ValueError("empty query")
    return {"query": query}


def _make_collect_sources(coordinator: Coordinator) -> Callable[[PulseState], Awaitable[dict]]:
    async def _collect_sources(state: PulseState) -> dict:
        # No try/except: the coordinator isolates per-source failures itself, so
        # anything raised here (cancellation, misconfiguration) must propagate.
        parallel_result = await coordinator(state["query"])
        return {"parallel_result": parallel_result}

    return _collect_sources


def _route_by_status(state: PulseState) -> NodeName:
    if state["parallel_result"].status is RunStatus.FAILED:
        return NodeName.FINALIZE_FAILURE
    return NodeName.FINALIZE_RESULTS


def _finalize_results(state: PulseState) -> dict:
    return {"result": state["parallel_result"]}


def _finalize_failure(state: PulseState) -> dict:
    return {"result": state["parallel_result"]}


def build_research_graph(coordinator: Coordinator):
    """Compile the research workflow once; invoke the result via `ainvoke`."""
    graph = StateGraph(PulseState, input_schema=PulseInput, output_schema=PulseOutput)
    graph.add_node(NodeName.INITIALIZE, _initialize_state)
    graph.add_node(NodeName.COLLECT_SOURCES, _make_collect_sources(coordinator))
    graph.add_node(NodeName.FINALIZE_RESULTS, _finalize_results)
    graph.add_node(NodeName.FINALIZE_FAILURE, _finalize_failure)

    graph.set_entry_point(NodeName.INITIALIZE)
    graph.add_edge(NodeName.INITIALIZE, NodeName.COLLECT_SOURCES)
    graph.add_conditional_edges(
        NodeName.COLLECT_SOURCES,
        _route_by_status,
        {
            NodeName.FINALIZE_RESULTS: NodeName.FINALIZE_RESULTS,
            NodeName.FINALIZE_FAILURE: NodeName.FINALIZE_FAILURE,
        },
    )
    graph.add_edge(NodeName.FINALIZE_RESULTS, END)
    graph.add_edge(NodeName.FINALIZE_FAILURE, END)

    return graph.compile()
