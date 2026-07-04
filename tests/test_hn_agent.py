"""Tests for pulse.agents.hn_agent — the HN-specific business logic only.

Generic ReAct engine mechanics (retry/stop/trace/no-results handling) are
covered by tests/test_react_loop.py against a synthetic config. These tests
only check that hn_agent builds the right Hacker News business logic
(collector binding, prompts, reason-context wording, score payload shape,
thresholds) and wires it into the engine correctly.
"""

from __future__ import annotations

import pytest

import pulse.agents.hn_agent as hn_agent
import pulse.llm as llm_module
from pulse.models import (
    ReasonDecision,
    Source,
    SourceBatchScore,
    SourceItem,
    StopReason,
    TraceEvent,
    TraceKind,
)

ARTICLE = SourceItem(
    title="LangGraph 2.0 released",
    url="https://news.ycombinator.com/item?id=1",
    score=0.9,
    summary="LangGraph 2.0 introduces streaming support.",
    source=Source.HACKER_NEWS,
)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    # Stub out load_dotenv so these tests are hermetic regardless of a real
    # local .env file (which may itself set OPENROUTER_API_KEY). Model chains
    # are plain code constants now, so no model env vars are needed here.
    monkeypatch.setattr(llm_module, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    # Keep live-progress wiring deterministic regardless of the host shell.
    monkeypatch.delenv("PULSE_LOG_LEVEL", raising=False)
    monkeypatch.delenv("PULSE_VERBOSE", raising=False)


def test_config_wires_hn_business_logic() -> None:
    config = hn_agent._config()

    assert config.score_threshold == hn_agent.SCORE_THRESHOLD
    assert config.max_iterations == hn_agent.MAX_ITERATIONS
    assert config.recursion_limit == hn_agent.RECURSION_LIMIT
    assert config.action_name == hn_agent.ACTION_NAME
    assert config.reason_system_prompt == hn_agent.REASON_SYSTEM_PROMPT
    assert config.observe_system_prompt == hn_agent.OBSERVE_SYSTEM_PROMPT
    assert config.reason_llm.func is hn_agent.complete_structured
    assert config.reason_llm.keywords["models"] == hn_agent.REASON_MODELS
    assert config.observe_llm.func is hn_agent.complete_structured
    assert config.observe_llm.keywords["models"] == hn_agent.OBSERVE_MODELS
    assert config.build_reason_context is hn_agent._build_reason_context
    assert config.build_score_payload is hn_agent._build_score_payload
    assert config.on_step is None


def test_live_progress_disabled_by_default() -> None:
    assert hn_agent._live_progress_enabled() is False


def test_debug_log_level_alone_does_not_enable_live_progress(monkeypatch) -> None:
    """Live progress is deliberately independent of PULSE_LOG_LEVEL: DEBUG
    already prints its own per-node detail via `logging`, so tying the live
    printer to DEBUG too would triple the output for the same events."""
    monkeypatch.setenv("PULSE_LOG_LEVEL", "DEBUG")
    assert hn_agent._live_progress_enabled() is False


def test_live_progress_enabled_by_verbose_flag(monkeypatch) -> None:
    monkeypatch.setenv("PULSE_VERBOSE", "1")
    assert hn_agent._live_progress_enabled() is True


def test_config_wires_on_step_printer_when_live_progress_enabled(monkeypatch) -> None:
    monkeypatch.setenv("PULSE_VERBOSE", "1")

    config = hn_agent._config()

    assert config.on_step is hn_agent._print_step


def test_print_step_writes_to_stderr(capsys) -> None:
    event = TraceEvent(kind=TraceKind.REASON, message="thinking")

    hn_agent._print_step(event)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Reason: thinking" in captured.err


def test_print_step_surfaces_query_when_not_already_in_message(capsys) -> None:
    event = TraceEvent(kind=TraceKind.REASON, message="thinking", query="AI LLM refined")

    hn_agent._print_step(event)

    assert "query='AI LLM refined'" in capsys.readouterr().err


def test_print_step_does_not_duplicate_query_already_in_message(capsys) -> None:
    event = TraceEvent(
        kind=TraceKind.ACT,
        message='tavily_hn("AI LLM refined") -> 3 results',
        query="AI LLM refined",
    )

    hn_agent._print_step(event)

    assert capsys.readouterr().err.count("AI LLM refined") == 1


def test_search_fn_calls_tavily_with_hacker_news_source(monkeypatch) -> None:
    calls = []

    def _fake_search_articles(query, source, *, max_results=10):
        calls.append((query, source, max_results))
        return [ARTICLE]

    monkeypatch.setattr(hn_agent, "search_articles", _fake_search_articles)

    articles = hn_agent._search("AI LLM", 5)

    assert articles == [ARTICLE]
    assert calls == [("AI LLM", Source.HACKER_NEWS, 5)]


def test_build_score_payload_maps_item_fields() -> None:
    payload = hn_agent._build_score_payload([ARTICLE])

    assert payload == [
        {
            "title": ARTICLE.title,
            "url": ARTICLE.url,
            "summary": ARTICLE.summary,
            "source": str(ARTICLE.source),
        }
    ]


def _base_state(**overrides) -> hn_agent.ReActState:
    state: hn_agent.ReActState = {
        "query": "AI LLM",
        "max_results": 10,
        "iteration": 0,
        "items": [],
        "best_score": 0.0,
        "last_score": 0.0,
        "done": False,
        "stop_reason": None,
        "trace": [],
    }
    state.update(overrides)
    return state


def test_reason_context_on_first_iteration_has_no_feedback() -> None:
    context = hn_agent._build_reason_context(_base_state(), hn_agent._config())

    assert context == "Current query: AI LLM"


def test_reason_context_includes_score_remaining_and_titles() -> None:
    state = _base_state(iteration=1, last_score=0.42, items=[ARTICLE])

    context = hn_agent._build_reason_context(state, hn_agent._config())

    assert f"attempt 1 of {hn_agent.MAX_ITERATIONS}" in context
    assert "0.42" in context
    assert f"{hn_agent.MAX_ITERATIONS - 1} attempt" in context
    assert ARTICLE.title in context


def test_reason_context_reflects_config_max_iterations_not_module_constant() -> None:
    """Regression: the context must track config.max_iterations, not a module
    constant baked in at definition time — otherwise a config built with a
    different max_iterations would silently diverge from the engine's actual
    stop condition."""
    state = _base_state(iteration=1, last_score=0.5)
    config = hn_agent._config()
    config.max_iterations = 10

    context = hn_agent._build_reason_context(state, config)

    assert "attempt 1 of 10" in context
    assert "9 attempt" in context


def test_reason_context_caps_title_preview() -> None:
    articles = [
        SourceItem(
            title=f"Article {i}",
            url=f"u{i}",
            score=0.5,
            summary="s",
            source=Source.HACKER_NEWS,
        )
        for i in range(hn_agent.PREVIEW_TITLE_COUNT + 3)
    ]
    state = _base_state(iteration=1, last_score=0.5, items=articles)

    context = hn_agent._build_reason_context(state, hn_agent._config())

    assert "Article 0" in context
    assert f"Article {hn_agent.PREVIEW_TITLE_COUNT}" not in context


def test_run_hn_react_end_to_end_with_hn_wiring(monkeypatch) -> None:
    def _fake_search_articles(query, source, *, max_results=10):
        return [ARTICLE]

    def _fake_complete(messages, models, response_model):
        if response_model is ReasonDecision:
            return ReasonDecision(thought="look for AI news", query="AI LLM refined")
        if response_model is SourceBatchScore:
            return SourceBatchScore(relevance=0.9, novelty=0.9, quality=0.9)
        raise AssertionError(f"unexpected response_model: {response_model}")

    monkeypatch.setattr(hn_agent, "search_articles", _fake_search_articles)
    monkeypatch.setattr(hn_agent, "complete_structured", _fake_complete)

    result = hn_agent.run_hn_react(query="AI LLM")

    assert result.stop_reason == StopReason.SCORE_THRESHOLD
    assert result.items == [ARTICLE]
    act_event = next(e for e in result.trace if e.kind == TraceKind.ACT)
    assert act_event.message.startswith(f'{hn_agent.ACTION_NAME}("AI LLM refined")')


def test_fetch_hn_articles_returns_articles_from_run_hn_react(monkeypatch) -> None:
    def _fake_search_articles(query, source, *, max_results=10):
        return [ARTICLE]

    def _fake_complete(messages, models, response_model):
        if response_model is ReasonDecision:
            return ReasonDecision(thought="t", query="q")
        if response_model is SourceBatchScore:
            return SourceBatchScore(relevance=0.9, novelty=0.9, quality=0.9)
        raise AssertionError(f"unexpected response_model: {response_model}")

    monkeypatch.setattr(hn_agent, "search_articles", _fake_search_articles)
    monkeypatch.setattr(hn_agent, "complete_structured", _fake_complete)

    articles = hn_agent.fetch_hn_articles(query="AI LLM")

    assert articles == [ARTICLE]
