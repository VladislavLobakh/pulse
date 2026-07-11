"""ReAct pattern (reason -> act -> observe) — engine and its LLM contracts.

Owns only the pattern mechanics: graph shape, iteration counting, stop/retry,
trace accumulation, and the Pydantic contracts its LLM steps must return.
Every source-specific concern (search, LLM calls, prompt wording, payload
shape, action label) is injected via `ReActConfig`; this module never imports
anything source- or gateway-specific.

Nodes log enter/exit via stdlib `logging` (`PULSE_LOG_LEVEL`), and each trace
event is also handed to `config.on_step` as it happens, for live progress.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from pulse.logging_config import get_logger
from pulse.models import SourceItemList

logger = get_logger(__name__)

DEFAULT_ACTION_NAME = "search"
DEFAULT_SCORE_THRESHOLD = 0.75
DEFAULT_MAX_ITERATIONS = 3
DEFAULT_RECURSION_LIMIT = 10


# --- LLM output contracts (Pydantic — Instructor requires Pydantic) ---


class ReasonDecision(BaseModel):
    must_keep_terms: list[str] = Field(
        default_factory=list,
        description="Terms from the ORIGINAL user query that every generated "
        "query must preserve: named technologies, products, acronyms, quoted "
        "phrases, negative terms (-term), and operators (site:...). Empty "
        "only when the original query names no concrete terms at all.",
    )
    thought: str = Field(
        description="Brief reasoning for why this query is the best next "
        "search, given the original user query and any feedback on previous "
        "attempts."
    )
    query: str = Field(
        description="The next search query to run. Must contain every entry "
        "of `must_keep_terms` (close spelling variants allowed) and stay on "
        "the topic of the original user query."
    )


class SourceBatchScore(BaseModel):
    relevance: float = Field(
        ge=0,
        le=1,
        description="How closely the batch matches the ORIGINAL user query "
        "(0 = off-topic or drifted to a different subject, 1 = squarely on "
        "the topic the user asked for).",
    )
    novelty: float = Field(
        ge=0,
        le=1,
        description="How much new information the batch adds beyond content "
        "already known or previously seen (0 = stale/repeat, 1 = fresh).",
    )
    quality: float = Field(
        ge=0,
        le=1,
        description="Editorial/technical quality of the items themselves "
        "(0 = low-effort or spam, 1 = well-sourced and substantive).",
    )

    @property
    def overall(self) -> float:
        return (self.relevance + self.novelty + self.quality) / 3


# --- Run result + trace (returned to callers, not LLM outputs) ---


class StopReason(StrEnum):
    SCORE_THRESHOLD = "score_threshold"
    MAX_ITERATIONS = "max_iterations"
    NO_RESULTS = "no_results"
    ERROR = "error"


class TraceKind(StrEnum):
    REASON = "reason"
    ACT = "act"
    OBSERVE = "observe"


@dataclass
class TraceEvent:
    kind: TraceKind
    message: str
    query: str | None = None
    result_count: int | None = None
    score: float | None = None


@dataclass
class ReActResult:
    items: SourceItemList
    stop_reason: StopReason
    trace: list[TraceEvent] = field(default_factory=list)
    best_score: float = 0.0
    iterations: int = 0


# --- Engine ---


class NodeName(StrEnum):
    REASON = "reason"
    ACT = "act"
    OBSERVE = "observe"
    NO_RESULTS = "no_results"


class ReActState(TypedDict):
    original_query: str  # the user's query verbatim — the intent contract, never rewritten
    query: str  # the query the next act step will run — rewritten by reason each iteration
    max_results: int
    iteration: int
    items: SourceItemList  # batch from the most recent act (overwritten every iteration)
    best_items: SourceItemList  # batch that earned best_score — what the run returns
    best_score: float  # running max score seen across all iterations
    last_score: float  # score from the most recent observe (used for reasoning)
    done: bool
    stop_reason: StopReason | None
    trace: list[TraceEvent]


# (query, max_results) -> results. Each source agent binds this to its own collector.
SearchFn = Callable[[str, int], SourceItemList]

# Mirrors pulse.llm.complete_structured with the model chain already bound, so
# the loop never imports an LLM gateway.
StructuredLLMFn = Callable[..., BaseModel]

# Formats the current item batch into whatever representation the scoring
# LLM call should see (e.g. title/url/summary for HN, authors/abstract for ArXiv).
ScorePayloadBuilder = Callable[[SourceItemList], object]

# Builds the reason step's user message (source-specific wording). Takes
# `config` so builders read live thresholds instead of baking in constants.
ReasonContextBuilder = Callable[["ReActState", "ReActConfig"], str]

# Called with each TraceEvent as it happens (not just once at the end of the
# run) — a source agent wires this up for live progress output. Optional.
OnStepCallback = Callable[[TraceEvent], None]


@dataclass
class ReActConfig:
    """Business logic for one source's ReAct run — supplied by the source agent.

    Everything here answers "how does this source think, search, and evaluate
    quality"; the engine itself only answers "how does reason -> act -> observe
    -> stop/retry work".
    """

    search_fn: SearchFn
    reason_llm: StructuredLLMFn
    observe_llm: StructuredLLMFn
    reason_system_prompt: str
    observe_system_prompt: str
    build_reason_context: ReasonContextBuilder
    build_score_payload: ScorePayloadBuilder
    action_name: str = DEFAULT_ACTION_NAME
    score_threshold: float = DEFAULT_SCORE_THRESHOLD
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    recursion_limit: int = DEFAULT_RECURSION_LIMIT
    on_step: OnStepCallback | None = None


def step_suffix(event: TraceEvent) -> str:
    # Only surface the query separately when the message doesn't already embed
    # it (the act event's message already reads `action("query") -> N results`).
    if event.query and event.query not in event.message:
        return f" (query={event.query!r})"
    return ""


def _emit(config: ReActConfig, state: ReActState, event: TraceEvent) -> list[TraceEvent]:
    logger.info("%s: %s%s", event.kind.capitalize(), event.message, step_suffix(event))
    if config.on_step is not None:
        config.on_step(event)
    return [*state["trace"], event]


def build_reason_messages(state: ReActState, config: ReActConfig) -> list[dict]:
    return [
        {"role": "system", "content": config.reason_system_prompt},
        {"role": "user", "content": config.build_reason_context(state, config)},
    ]


def _make_reason_node(config: ReActConfig) -> Callable[[ReActState], dict]:
    def _reason_node(state: ReActState) -> dict:
        logger.debug("Entering node=%s iteration=%d", NodeName.REASON, state["iteration"])
        messages = build_reason_messages(state, config)
        logger.debug("Reason context: %s", messages[-1]["content"])
        decision = config.reason_llm(messages=messages, response_model=ReasonDecision)
        logger.debug("ReasonDecision query=%r thought=%r", decision.query, decision.thought[:200])
        event = TraceEvent(kind=TraceKind.REASON, message=decision.thought, query=decision.query)
        result = {"query": decision.query, "trace": _emit(config, state, event)}
        logger.debug("Exiting node=%s next_query=%r", NodeName.REASON, decision.query)
        return result

    return _reason_node


def _make_act_node(config: ReActConfig) -> Callable[[ReActState], dict]:
    def _act_node(state: ReActState) -> dict:
        logger.debug(
            "Entering node=%s action=%s query=%r", NodeName.ACT, config.action_name, state["query"]
        )
        items = config.search_fn(state["query"], state["max_results"])
        event = TraceEvent(
            kind=TraceKind.ACT,
            message=f'{config.action_name}("{state["query"]}") -> {len(items)} results',
            query=state["query"],
            result_count=len(items),
        )
        result = {"items": items, "trace": _emit(config, state, event)}
        logger.debug("Exiting node=%s result_count=%d", NodeName.ACT, len(items))
        return result

    return _act_node


def _has_results(state: ReActState) -> NodeName:
    return NodeName.OBSERVE if state["items"] else NodeName.NO_RESULTS


def _make_no_results_node(config: ReActConfig) -> Callable[[ReActState], dict]:
    def _no_results_node(state: ReActState) -> dict:
        logger.debug("Entering node=%s", NodeName.NO_RESULTS)
        event = TraceEvent(kind=TraceKind.OBSERVE, message="no results -> stop (NO_RESULTS)")
        result = {
            "iteration": state["iteration"] + 1,
            "done": True,
            "stop_reason": StopReason.NO_RESULTS,
            "trace": _emit(config, state, event),
        }
        logger.debug("Exiting node=%s stop_reason=%s", NodeName.NO_RESULTS, StopReason.NO_RESULTS)
        return result

    return _no_results_node


def build_scoring_input(state: ReActState, config: ReActConfig) -> dict:
    """Both queries go to the scorer so drift is judged against user intent,
    not the reason step's own rewrite."""
    return {
        "original_query": state["original_query"],
        "generated_query": state["query"],
        "results": config.build_score_payload(state["items"]),
    }


def build_observe_messages(state: ReActState, config: ReActConfig) -> list[dict]:
    return [
        {"role": "system", "content": config.observe_system_prompt},
        {"role": "user", "content": json.dumps(build_scoring_input(state, config))},
    ]


def _make_observe_node(config: ReActConfig) -> Callable[[ReActState], dict]:
    def _observe_node(state: ReActState) -> dict:
        logger.debug("Entering node=%s iteration=%d", NodeName.OBSERVE, state["iteration"])
        result = config.observe_llm(
            messages=build_observe_messages(state, config),
            response_model=SourceBatchScore,
        )
        logger.debug(
            "Score breakdown relevance=%.2f novelty=%.2f quality=%.2f overall=%.2f",
            result.relevance,
            result.novelty,
            result.quality,
            result.overall,
        )
        iteration = state["iteration"] + 1
        # Updated as a pair so the returned batch and its reported score can
        # never describe different attempts.
        if result.overall > state["best_score"]:
            best_score, best_items = result.overall, state["items"]
        else:
            best_score, best_items = state["best_score"], state["best_items"]
        done = False
        stop_reason: StopReason | None = None
        if result.overall >= config.score_threshold:
            done = True
            stop_reason = StopReason.SCORE_THRESHOLD
        elif iteration >= config.max_iterations:
            done = True
            stop_reason = StopReason.MAX_ITERATIONS

        message = f"score={result.overall:.2f} -> "
        message += f"stop ({stop_reason})" if done else "continue"
        event = TraceEvent(kind=TraceKind.OBSERVE, message=message, score=result.overall)

        out = {
            "best_score": best_score,
            "best_items": best_items,
            "last_score": result.overall,
            "iteration": iteration,
            "done": done,
            "stop_reason": stop_reason,
            "trace": _emit(config, state, event),
        }
        logger.debug("Exiting node=%s done=%s stop_reason=%s", NodeName.OBSERVE, done, stop_reason)
        return out

    return _observe_node


def _should_continue(state: ReActState) -> str:
    return END if state["done"] else NodeName.REASON


def build_graph(config: ReActConfig):
    graph = StateGraph(ReActState)
    graph.add_node(NodeName.REASON, _make_reason_node(config))
    graph.add_node(NodeName.ACT, _make_act_node(config))
    graph.add_node(NodeName.OBSERVE, _make_observe_node(config))
    graph.add_node(NodeName.NO_RESULTS, _make_no_results_node(config))

    graph.set_entry_point(NodeName.REASON)
    graph.add_edge(NodeName.REASON, NodeName.ACT)
    graph.add_conditional_edges(
        NodeName.ACT,
        _has_results,
        {NodeName.OBSERVE: NodeName.OBSERVE, NodeName.NO_RESULTS: NodeName.NO_RESULTS},
    )
    graph.add_edge(NodeName.NO_RESULTS, END)
    graph.add_conditional_edges(
        NodeName.OBSERVE,
        _should_continue,
        {NodeName.REASON: NodeName.REASON, END: END},
    )

    return graph.compile()


def make_initial_state(query: str, max_results: int) -> ReActState:
    return {
        "original_query": query,
        "query": query,
        "max_results": max_results,
        "iteration": 0,
        "items": [],
        "best_items": [],
        "best_score": 0.0,
        "last_score": 0.0,
        "done": False,
        "stop_reason": None,
        "trace": [],
    }


def run_react(config: ReActConfig, query: str, max_results: int) -> ReActResult:
    logger.info("Starting ReAct run query=%r max_results=%d", query, max_results)
    graph = build_graph(config)
    initial_state = make_initial_state(query, max_results)
    final_state = graph.invoke(initial_state, config={"recursion_limit": config.recursion_limit})

    # The graph only reaches END via observe_node or no_results_node, both of which
    # always set stop_reason — this fallback is defensive, not the primary path.
    stop_reason = final_state["stop_reason"] or StopReason.ERROR
    logger.info(
        "Finished ReAct run stop_reason=%s iterations=%d best_score=%.2f",
        stop_reason,
        final_state["iteration"],
        final_state["best_score"],
    )
    return ReActResult(
        final_state["best_items"],
        stop_reason,
        trace=final_state["trace"],
        best_score=final_state["best_score"],
        iterations=final_state["iteration"],
    )
