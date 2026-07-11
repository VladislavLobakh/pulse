"""Tests for pulse.main — the CLI entry point, no real network or LLM calls."""

from __future__ import annotations

import pytest

import pulse.main as main_module
from pulse.models import Source, SourceItem
from pulse.patterns.react import ReActResult, StopReason, TraceEvent, TraceKind

ARTICLE = SourceItem(
    title="LangGraph 2.0 released",
    url="https://news.ycombinator.com/item?id=1",
    score=0.9,
    summary="LangGraph 2.0 introduces streaming support.",
    source=Source.HACKER_NEWS,
)


def test_main_parses_query_argument_and_passes_it_through(monkeypatch, capsys) -> None:
    seen_queries = []

    def _fake_run_hn_react(query):
        seen_queries.append(query)
        return ReActResult(
            items=[ARTICLE],
            stop_reason=StopReason.SCORE_THRESHOLD,
            trace=[TraceEvent(kind=TraceKind.REASON, message="m")],
            best_score=0.9,
            iterations=1,
        )

    monkeypatch.setattr(main_module, "run_hn_react", _fake_run_hn_react)

    main_module.main(["custom query"])

    assert seen_queries == ["custom query"]
    out = capsys.readouterr().out
    assert "Reason / Act / Observe trace" in out
    assert "SCORE_THRESHOLD (not looping)" in out
    assert "LangGraph 2.0 released" in out
    assert "Total: 1 articles collected." in out


def test_main_requires_a_query_argument(capsys) -> None:
    """The query always comes from the caller — there is no built-in default
    topic, so invoking the CLI without one is a usage error."""
    with pytest.raises(SystemExit) as excinfo:
        main_module.main([])

    assert excinfo.value.code == 2
    assert "query" in capsys.readouterr().err


def test_main_warns_when_below_minimum_articles(monkeypatch, capsys) -> None:
    def _fake_run_hn_react(query):
        return ReActResult(items=[], stop_reason=StopReason.NO_RESULTS, trace=[])

    monkeypatch.setattr(main_module, "run_hn_react", _fake_run_hn_react)

    main_module.main(["some query"])

    err = capsys.readouterr().err
    assert "WARNING" in err
