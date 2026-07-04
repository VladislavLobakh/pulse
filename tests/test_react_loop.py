"""Tests for pulse.agents.react_loop — the generic ReAct engine, source-agnostic.

Every source-specific concern (search, LLM call, reasoning-context wording,
scoring payload shape, action label) is supplied via `ReActConfig`, so these
tests need zero monkeypatching — everything is plain function injection,
using a synthetic ("item") domain with no Tavily/HN references at all.
"""

from __future__ import annotations

import pytest

import pulse.agents.react_loop as react_loop
from pulse.models import ReasonDecision, Source, SourceBatchScore, SourceItem, StopReason, TraceKind

ITEM = SourceItem(
    title="Some paper",
    url="https://example.com/1",
    score=0.9,
    summary="A summary.",
    source=Source.ARXIV,
)

REASON_PROMPT = "reason about the next search"
OBSERVE_PROMPT = "score this batch"


def _make_search_fn(batches: list[list[SourceItem]]):
    calls = {"n": 0}

    def _search(query: str, max_results: int) -> list[SourceItem]:
        batch = batches[min(calls["n"], len(batches) - 1)]
        calls["n"] += 1
        return batch

    _search.calls = calls
    return _search


def _make_structured_llm(reason_thoughts: list[str], scores: list[SourceBatchScore]):
    state = {"reason_calls": 0, "score_calls": 0, "reason_messages": []}

    def _structured_llm(messages, response_model):
        if response_model is ReasonDecision:
            i = min(state["reason_calls"], len(reason_thoughts) - 1)
            state["reason_calls"] += 1
            state["reason_messages"].append(messages[-1]["content"])
            return ReasonDecision(thought=reason_thoughts[i], query="refined query")
        if response_model is SourceBatchScore:
            i = min(state["score_calls"], len(scores) - 1)
            state["score_calls"] += 1
            return scores[i]
        raise AssertionError(f"unexpected response_model: {response_model}")

    _structured_llm.state = state
    return _structured_llm


def _reason_context(state, config) -> str:
    return (
        f"query={state['query']} iteration={state['iteration']} "
        f"last_score={state['last_score']} max_iterations={config.max_iterations}"
    )


def _score_payload(items) -> list[str]:
    return [item.title for item in items]


def _config(search_fn, llm, **overrides) -> react_loop.ReActConfig:
    defaults = {
        "search_fn": search_fn,
        "reason_llm": llm,
        "observe_llm": llm,
        "reason_system_prompt": REASON_PROMPT,
        "observe_system_prompt": OBSERVE_PROMPT,
        "build_reason_context": _reason_context,
        "build_score_payload": _score_payload,
    }
    defaults.update(overrides)
    return react_loop.ReActConfig(**defaults)


def test_stops_on_high_score() -> None:
    search = _make_search_fn([[ITEM]])
    llm = _make_structured_llm(
        ["look for results"], [SourceBatchScore(relevance=0.9, novelty=0.9, quality=0.9)]
    )

    result = react_loop.run_react(_config(search, llm), query="q", max_results=10)

    assert result.stop_reason == StopReason.SCORE_THRESHOLD
    assert result.iterations == 1
    assert llm.state["score_calls"] == 1


def test_reasons_again_on_low_score_then_bounded() -> None:
    search = _make_search_fn([[ITEM]])
    low_score = SourceBatchScore(relevance=0.2, novelty=0.2, quality=0.2)
    llm = _make_structured_llm(["t1", "t2", "t3"], [low_score])

    config = _config(search, llm, max_iterations=3)
    result = react_loop.run_react(config, query="q", max_results=10)

    assert result.stop_reason == StopReason.MAX_ITERATIONS
    assert result.iterations == 3
    assert llm.state["reason_calls"] == 3
    assert llm.state["score_calls"] == 3


def test_empty_results_stops_without_scoring_and_emits_trace_event() -> None:
    search = _make_search_fn([[]])
    llm = _make_structured_llm(["t1"], [SourceBatchScore(relevance=0.9, novelty=0.9, quality=0.9)])

    result = react_loop.run_react(_config(search, llm), query="q", max_results=10)

    assert result.stop_reason == StopReason.NO_RESULTS
    assert llm.state["score_calls"] == 0
    assert result.items == []
    assert result.iterations == 1
    assert result.trace[-1].kind == TraceKind.OBSERVE
    assert "no results" in result.trace[-1].message


def test_trace_contains_reason_act_observe_events() -> None:
    search = _make_search_fn([[ITEM]])
    llm = _make_structured_llm(["t1"], [SourceBatchScore(relevance=0.9, novelty=0.9, quality=0.9)])

    result = react_loop.run_react(_config(search, llm), query="q", max_results=10)

    kinds = [event.kind for event in result.trace]
    assert kinds == [TraceKind.REASON, TraceKind.ACT, TraceKind.OBSERVE]


def test_act_trace_uses_configured_action_name() -> None:
    search = _make_search_fn([[ITEM]])
    llm = _make_structured_llm(["t1"], [SourceBatchScore(relevance=0.9, novelty=0.9, quality=0.9)])
    config = _config(search, llm, action_name="arxiv_search")

    result = react_loop.run_react(config, query="q", max_results=10)

    act_event = next(e for e in result.trace if e.kind == TraceKind.ACT)
    assert act_event.message.startswith('arxiv_search("refined query")')


def test_best_score_tracks_running_max_not_last_attempt() -> None:
    search = _make_search_fn([[ITEM]])
    high_then_low = [
        SourceBatchScore(relevance=0.9, novelty=0.9, quality=0.9),
        SourceBatchScore(relevance=0.1, novelty=0.1, quality=0.1),
    ]
    llm = _make_structured_llm(["t1", "t2"], high_then_low)
    # threshold unreachable so a second iteration happens despite the first
    # attempt already scoring higher than it.
    config = _config(search, llm, score_threshold=2.0, max_iterations=2)

    result = react_loop.run_react(config, query="q", max_results=10)

    assert result.best_score == pytest.approx(high_then_low[0].overall)


def test_reason_llm_and_observe_llm_are_independent_callables() -> None:
    """The engine must call config.reason_llm for the reason step and
    config.observe_llm for the observe step — never the same callable for
    both, so each ReAct operation can be backed by its own model chain."""
    search = _make_search_fn([[ITEM]])
    reason_calls = []
    observe_calls = []

    def _reason_llm(messages, response_model):
        reason_calls.append(response_model)
        return ReasonDecision(thought="t", query="refined query")

    def _observe_llm(messages, response_model):
        observe_calls.append(response_model)
        return SourceBatchScore(relevance=0.9, novelty=0.9, quality=0.9)

    config = react_loop.ReActConfig(
        search_fn=search,
        reason_llm=_reason_llm,
        observe_llm=_observe_llm,
        reason_system_prompt=REASON_PROMPT,
        observe_system_prompt=OBSERVE_PROMPT,
        build_reason_context=_reason_context,
        build_score_payload=_score_payload,
    )

    result = react_loop.run_react(config, query="q", max_results=10)

    assert result.stop_reason == StopReason.SCORE_THRESHOLD
    assert reason_calls == [ReasonDecision]
    assert observe_calls == [SourceBatchScore]


def test_on_step_called_for_every_trace_event_as_it_happens() -> None:
    """on_step must fire per step during the run (live progress), not only be
    derivable from the final trace — so it should be called once per event,
    in the same order the trace ends up in."""
    search = _make_search_fn([[ITEM]])
    llm = _make_structured_llm(["t1"], [SourceBatchScore(relevance=0.9, novelty=0.9, quality=0.9)])
    seen_events = []

    config = _config(search, llm, on_step=seen_events.append)
    result = react_loop.run_react(config, query="q", max_results=10)

    assert seen_events == result.trace
    assert [e.kind for e in seen_events] == [TraceKind.REASON, TraceKind.ACT, TraceKind.OBSERVE]


def test_on_step_called_on_no_results_path() -> None:
    search = _make_search_fn([[]])
    llm = _make_structured_llm(["t1"], [SourceBatchScore(relevance=0.9, novelty=0.9, quality=0.9)])
    seen_events = []

    config = _config(search, llm, on_step=seen_events.append)
    result = react_loop.run_react(config, query="q", max_results=10)

    assert seen_events == result.trace
    assert seen_events[-1].kind == TraceKind.OBSERVE
    assert "no results" in seen_events[-1].message


def test_on_step_defaults_to_none_and_is_optional() -> None:
    search = _make_search_fn([[ITEM]])
    llm = _make_structured_llm(["t1"], [SourceBatchScore(relevance=0.9, novelty=0.9, quality=0.9)])

    config = _config(search, llm)

    assert config.on_step is None
    # must not raise even though no callback was supplied
    react_loop.run_react(config, query="q", max_results=10)


def test_reason_and_score_builders_are_invoked_generically() -> None:
    search = _make_search_fn([[ITEM]])
    llm = _make_structured_llm(["t1"], [SourceBatchScore(relevance=0.9, novelty=0.9, quality=0.9)])
    seen_payloads = []

    def _score_payload_spy(items):
        seen_payloads.append(items)
        return [item.title for item in items]

    config = _config(search, llm, build_score_payload=_score_payload_spy)
    react_loop.run_react(config, query="q", max_results=10)

    messages = llm.state["reason_messages"]
    assert messages[0] == (
        f"query=q iteration=0 last_score=0.0 max_iterations={config.max_iterations}"
    )
    assert seen_payloads == [[ITEM]]
