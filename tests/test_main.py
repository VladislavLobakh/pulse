"""Tests for pulse.main — the CLI entry point, no real network or LLM calls.

Every test that calls `main()` must stub `build_analyzer`; without it the real
analyzer reaches the provider and the suite stops being offline.
"""

from __future__ import annotations

import asyncio

import pytest

import pulse.main as main_module
from pulse.llm import ProviderBillingError, ProviderConfigurationError
from pulse.models import Source, SourceItem, SourceItemList
from pulse.patterns.parallel import ParallelRunResult, RunStatus, SourceOutput, SourceRunner
from pulse.patterns.topic_signal import (
    AnalysisRunResult,
    AnalysisStatus,
    EventType,
    TopicSignal,
    TopicSignalResult,
)


def _item(source: Source, url: str, title: str) -> SourceItem:
    return SourceItem(title=title, url=url, score=0.9, summary=f"{title} summary.", source=source)


def _signal(topic: str = "Claude Opus 4.8") -> TopicSignal:
    return TopicSignal(
        topic=topic,
        event_type=EventType.RELEASE,
        key_change="Made generally available.",
        relevance=0.95,
        confidence=0.9,
        evidence="The item says it shipped today.",
    )


def _stub_analyzer(monkeypatch, results=None, raises: BaseException | None = None) -> list:
    """Replace the production analyzer binding. Returns the recorded calls."""
    calls: list[tuple[str, SourceItemList]] = []

    async def analyzer(query: str, items: SourceItemList) -> list[TopicSignalResult]:
        calls.append((query, items))
        if raises is not None:
            raise raises
        if results is not None:
            return results(items)
        return [
            TopicSignalResult(item=item, status=AnalysisStatus.SUCCESS, signal=_signal())
            for item in items
        ]

    monkeypatch.setattr(main_module, "build_analyzer", lambda: analyzer)
    return calls


def _ok_runner(source: Source, items: list[SourceItem]) -> SourceRunner:
    return SourceRunner(
        source=source, run=lambda query: SourceOutput(items=items, status=RunStatus.SUCCESS)
    )


def _failing_runner(source: Source) -> SourceRunner:
    def run(query: str) -> SourceOutput:
        raise RuntimeError("boom")

    return SourceRunner(source=source, run=run)


def _partial_runner(source: Source, items: list[SourceItem], error: str) -> SourceRunner:
    return SourceRunner(
        source=source,
        run=lambda query: SourceOutput(items=items, status=RunStatus.PARTIAL, error=error),
    )


def _recording_runners(calls: list[str]) -> list[SourceRunner]:
    def run(query: str) -> SourceOutput:
        calls.append(query)
        return SourceOutput(items=[], status=RunStatus.SUCCESS)

    return [
        SourceRunner(source=source, run=run)
        for source in (Source.HACKER_NEWS, Source.ARXIV, Source.YOUTUBE, Source.NEWSLETTER)
    ]


def test_build_runners_returns_all_four_sources_in_order() -> None:
    runners = main_module.build_runners()

    assert [r.source for r in runners] == [
        Source.HACKER_NEWS,
        Source.ARXIV,
        Source.YOUTUBE,
        Source.NEWSLETTER,
    ]


def test_main_requires_a_query_argument(monkeypatch, capsys) -> None:
    """The query always comes from the caller — there is no built-in default
    topic, so invoking the CLI without one is a usage error."""

    def _fail_if_called() -> list[SourceRunner]:
        raise AssertionError("build_runners should not be called for a missing query")

    monkeypatch.setattr(main_module, "build_runners", _fail_if_called)

    with pytest.raises(SystemExit) as excinfo:
        main_module.main([])

    assert excinfo.value.code == 2
    assert "query" in capsys.readouterr().err


@pytest.mark.parametrize("query", ["", "   "])
def test_main_empty_or_whitespace_query_exits_2_without_traceback(
    monkeypatch, capsys, query: str
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(main_module, "build_runners", lambda: _recording_runners(calls))
    analyzed = _stub_analyzer(monkeypatch)

    with pytest.raises(SystemExit) as excinfo:
        main_module.main([query])

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert calls == []
    assert analyzed == []


def test_main_operational_value_error_is_not_misclassified_as_input_error(monkeypatch) -> None:
    """An empty runner list makes `run_sources` raise a plain `ValueError` —
    an operational/config error, not a query problem — which must propagate
    instead of being caught as the CLI's clean input-error exit path."""
    monkeypatch.setattr(main_module, "build_runners", lambda: [])
    _stub_analyzer(monkeypatch)

    with pytest.raises(ValueError):
        main_module.main(["custom query"])


def test_main_builds_graph_from_coordinator_and_invokes_once(monkeypatch) -> None:
    factory_calls: list[object] = []
    invoke_calls: list[dict] = []

    class _FakeGraph:
        async def ainvoke(self, state: dict) -> dict:
            invoke_calls.append(state)
            return {
                "result": ParallelRunResult(results=[], items=[], status=RunStatus.SUCCESS),
                "analysis": AnalysisRunResult.completed([]),
            }

    fake_graph = _FakeGraph()

    def fake_build_research_graph(coordinator: object, analyzer: object) -> _FakeGraph:
        factory_calls.append((coordinator, analyzer))
        return fake_graph

    monkeypatch.setattr(main_module, "build_research_graph", fake_build_research_graph)
    _stub_analyzer(monkeypatch)

    main_module.main(["custom query"])

    assert len(factory_calls) == 1
    assert all(callable(dependency) for dependency in factory_calls[0])
    assert invoke_calls == [{"query": "custom query"}]


def test_main_run_sources_invoked_exactly_once_through_coordinator(monkeypatch, capsys) -> None:
    coordinator_calls: list[str] = []
    real_run_sources = main_module.run_sources

    async def spy(query: str, runners: list[SourceRunner]) -> ParallelRunResult:
        coordinator_calls.append(query)
        return await real_run_sources(query, runners)

    monkeypatch.setattr(main_module, "run_sources", spy)
    monkeypatch.setattr(main_module, "build_runners", lambda: _recording_runners([]))
    _stub_analyzer(monkeypatch)

    main_module.main(["custom query"])

    assert coordinator_calls == ["custom query"]


def test_main_all_sources_succeed_shows_success_summary(monkeypatch, capsys) -> None:
    runners = [
        _ok_runner(
            Source.HACKER_NEWS, [_item(Source.HACKER_NEWS, "https://a.example/1", "HN item")]
        ),
        _ok_runner(Source.ARXIV, [_item(Source.ARXIV, "https://a.example/2", "ArXiv item")]),
        _ok_runner(Source.YOUTUBE, [_item(Source.YOUTUBE, "https://a.example/3", "YouTube item")]),
        _ok_runner(
            Source.NEWSLETTER, [_item(Source.NEWSLETTER, "https://a.example/4", "Newsletter item")]
        ),
    ]
    monkeypatch.setattr(main_module, "build_runners", lambda: runners)
    _stub_analyzer(monkeypatch)

    main_module.main(["custom query"])

    out = capsys.readouterr().out
    for source in (Source.HACKER_NEWS, Source.ARXIV, Source.YOUTUBE, Source.NEWSLETTER):
        assert source.value in out
    lines = out.splitlines()
    source_lines = [
        line
        for line in lines
        if line.split(" ", 1)[0] in {"hacker_news", "arxiv", "youtube", "newsletter"}
    ]
    assert len(source_lines) == 4
    assert all("SUCCESS" in line for line in source_lines)
    assert "Aggregate: SUCCESS" in out
    assert "4 unique items" in out
    assert "Total: 4 items collected." in out
    assert "not looping" not in out
    assert "Reason / Act / Observe" not in out


def test_main_one_failure_shows_partial_and_identifies_failed_source(monkeypatch, capsys) -> None:
    runners = [
        _ok_runner(
            Source.HACKER_NEWS, [_item(Source.HACKER_NEWS, "https://a.example/1", "HN item")]
        ),
        _failing_runner(Source.ARXIV),
        _ok_runner(Source.YOUTUBE, [_item(Source.YOUTUBE, "https://a.example/3", "YouTube item")]),
        _ok_runner(
            Source.NEWSLETTER, [_item(Source.NEWSLETTER, "https://a.example/4", "Newsletter item")]
        ),
    ]
    monkeypatch.setattr(main_module, "build_runners", lambda: runners)
    _stub_analyzer(monkeypatch)

    main_module.main(["custom query"])

    out = capsys.readouterr().out
    assert "Aggregate: PARTIAL" in out
    lines = out.splitlines()
    arxiv_line = next(line for line in lines if line.startswith(Source.ARXIV.value))
    assert "FAILED" in arxiv_line
    assert "(RuntimeError)" in arxiv_line
    assert "HN item" in out
    assert "YouTube item" in out
    assert "Newsletter item" in out
    assert "Total: 3 items collected." in out


def test_main_all_failures_exit_nonzero_without_item_listing(monkeypatch, capsys) -> None:
    runners = [
        _failing_runner(source)
        for source in (Source.HACKER_NEWS, Source.ARXIV, Source.YOUTUBE, Source.NEWSLETTER)
    ]
    monkeypatch.setattr(main_module, "build_runners", lambda: runners)
    _stub_analyzer(monkeypatch)

    with pytest.raises(SystemExit) as excinfo:
        main_module.main(["custom query"])

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "Aggregate: FAILED" in out
    # Per-source lines legitimately say "0 items"; what must never appear is
    # the combined item listing or its misleading total count.
    assert "items collected" not in out
    assert "items ===" not in out


def test_main_partial_source_error_reason_is_shown(monkeypatch, capsys) -> None:
    hn_items = [_item(Source.HACKER_NEWS, "https://a.example/1", "HN item")]
    runners = [
        _partial_runner(Source.HACKER_NEWS, hn_items, "below_min_articles"),
        _ok_runner(Source.ARXIV, []),
        _ok_runner(Source.YOUTUBE, []),
        _ok_runner(Source.NEWSLETTER, []),
    ]
    monkeypatch.setattr(main_module, "build_runners", lambda: runners)
    _stub_analyzer(monkeypatch)

    main_module.main(["custom query"])

    out = capsys.readouterr().out
    assert "(below_min_articles)" in out
    assert "Aggregate: PARTIAL" in out


def test_main_passes_query_to_coordinator(monkeypatch, capsys) -> None:
    seen_queries: list[str] = []

    def run(query: str) -> SourceOutput:
        seen_queries.append(query)
        return SourceOutput(items=[], status=RunStatus.SUCCESS)

    runners = [SourceRunner(source=r.source, run=run) for r in main_module.build_runners()]
    monkeypatch.setattr(main_module, "build_runners", lambda: runners)
    _stub_analyzer(monkeypatch)

    main_module.main(["custom query"])

    assert seen_queries == ["custom query"] * len(runners)


# --- One CLI invocation, one execution path ---


def test_one_cli_invocation_drives_one_pass_through_every_stage(monkeypatch, capsys) -> None:
    """Separate per-stage call counts can't rule out a second path. This drives
    the real graph composition once and counts every stage in that one run."""
    duplicate = "https://a.example/shared"
    runners = [
        _ok_runner(
            Source.HACKER_NEWS,
            [
                _item(Source.HACKER_NEWS, "https://a.example/1", "HN item"),
                _item(Source.HACKER_NEWS, duplicate, "Shared item"),
            ],
        ),
        _ok_runner(Source.ARXIV, [_item(Source.ARXIV, duplicate, "Shared item again")]),
    ]
    monkeypatch.setattr(main_module, "build_runners", lambda: runners)
    analyzed = _stub_analyzer(monkeypatch)

    factory_calls: list[tuple] = []
    invoke_calls: list[dict] = []
    real_factory = main_module.build_research_graph

    class _CountingGraph:
        def __init__(self, graph) -> None:
            self._graph = graph

        async def ainvoke(self, state: dict) -> dict:
            invoke_calls.append(state)
            return await self._graph.ainvoke(state)

    def counting_factory(coordinator, analyzer):
        factory_calls.append((coordinator, analyzer))
        return _CountingGraph(real_factory(coordinator, analyzer))

    monkeypatch.setattr(main_module, "build_research_graph", counting_factory)

    coordinator_calls: list[str] = []
    real_run_sources = main_module.run_sources

    async def spy(query: str, sources: list[SourceRunner]) -> ParallelRunResult:
        coordinator_calls.append(query)
        return await real_run_sources(query, sources)

    monkeypatch.setattr(main_module, "run_sources", spy)

    main_module.main(["custom query"])

    assert len(factory_calls) == 1
    assert invoke_calls == [{"query": "custom query"}]
    assert coordinator_calls == ["custom query"]
    assert len(analyzed) == 1
    query, items = analyzed[0]
    assert query == "custom query"
    # The analyzer sees the coordinator's ordered, deduped output — not raw
    # per-source items, and not a second collection pass.
    assert [i.url for i in items] == ["https://a.example/1", duplicate]


def test_build_analyzer_binds_production_models_and_sampling(monkeypatch) -> None:
    recorded: list[dict] = []

    def fake_complete_structured(**kwargs):
        recorded.append(kwargs)
        return _signal()

    monkeypatch.setattr(main_module, "complete_structured", fake_complete_structured)
    item = _item(Source.ARXIV, "https://a.example/1", "item")

    results = asyncio.run(main_module.build_analyzer()("custom query", [item]))

    assert len(recorded) == 1
    assert recorded[0]["models"] == main_module.ANALYSIS_MODELS
    assert recorded[0]["temperature"] == main_module.LLM_TEMPERATURE
    assert recorded[0]["max_tokens"] == main_module.LLM_MAX_TOKENS
    assert results[0].status is AnalysisStatus.SUCCESS


def test_analyze_llm_is_bound_to_the_structured_completion_gateway() -> None:
    from pulse.llm import complete_structured

    bound = main_module._analyze_llm()

    assert bound.func is complete_structured
    assert bound.keywords == {
        "models": main_module.ANALYSIS_MODELS,
        "temperature": main_module.LLM_TEMPERATURE,
        "max_tokens": main_module.LLM_MAX_TOKENS,
    }


# --- Analysis presentation and exit codes ---


def test_successful_analysis_renders_every_signal_field_and_exits_zero(monkeypatch, capsys) -> None:
    runners = [_ok_runner(Source.ARXIV, [_item(Source.ARXIV, "https://a.example/1", "ArXiv item")])]
    monkeypatch.setattr(main_module, "build_runners", lambda: runners)
    _stub_analyzer(monkeypatch)

    main_module.main(["custom query"])

    out = capsys.readouterr().out
    assert "topic: Claude Opus 4.8 (release)" in out
    assert "change: Made generally available." in out
    assert "signal: relevance 0.95 · confidence 0.90" in out
    assert "evidence: The item says it shipped today." in out
    assert "Analysis: SUCCESS — 1 analyzed, 0 failed" in out


def test_partial_analysis_exits_zero_and_shows_the_per_item_error(monkeypatch, capsys) -> None:
    items = [
        _item(Source.ARXIV, "https://a.example/1", "Good item"),
        _item(Source.ARXIV, "https://a.example/2", "Bad item"),
    ]
    runners = [_ok_runner(Source.ARXIV, items)]
    monkeypatch.setattr(main_module, "build_runners", lambda: runners)
    _stub_analyzer(
        monkeypatch,
        results=lambda collected: [
            TopicSignalResult(item=collected[0], status=AnalysisStatus.SUCCESS, signal=_signal()),
            TopicSignalResult(
                item=collected[1], status=AnalysisStatus.FAILED, error="ModelsExhaustedError"
            ),
        ],
    )

    main_module.main(["custom query"])

    out = capsys.readouterr().out
    assert "Good item" in out
    assert "Bad item" in out
    assert "analysis: FAILED (ModelsExhaustedError)" in out
    assert "Analysis: PARTIAL — 1 analyzed, 1 failed" in out


def test_all_items_failing_independently_exits_one_with_per_item_errors(
    monkeypatch, capsys
) -> None:
    items = [
        _item(Source.ARXIV, "https://a.example/1", "One"),
        _item(Source.ARXIV, "https://a.example/2", "Two"),
    ]
    runners = [_ok_runner(Source.ARXIV, items)]
    monkeypatch.setattr(main_module, "build_runners", lambda: runners)
    _stub_analyzer(
        monkeypatch,
        results=lambda collected: [
            TopicSignalResult(item=item, status=AnalysisStatus.FAILED, error="ModelsExhaustedError")
            for item in collected
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        main_module.main(["custom query"])

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "Total: 2 items collected." in out
    assert out.count("analysis: FAILED (ModelsExhaustedError)") == 2
    assert "Analysis: FAILED — 0 analyzed, 2 failed" in out


@pytest.mark.parametrize(
    "exc",
    [
        ProviderConfigurationError("OPENROUTER_API_KEY not set — check .env"),
        ProviderBillingError("402 payment required for account acct_secret"),
    ],
)
def test_shared_provider_failure_reports_once_and_keeps_the_item_listing(
    monkeypatch, capsys, exc: Exception
) -> None:
    items = [
        _item(Source.ARXIV, "https://a.example/1", "One"),
        _item(Source.ARXIV, "https://a.example/2", "Two"),
    ]
    runners = [_ok_runner(Source.ARXIV, items)]
    monkeypatch.setattr(main_module, "build_runners", lambda: runners)
    _stub_analyzer(monkeypatch, raises=exc)

    with pytest.raises(SystemExit) as excinfo:
        main_module.main(["custom query"])

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Aggregate: SUCCESS" in captured.out
    assert "Total: 2 items collected." in captured.out
    assert "One" in captured.out and "Two" in captured.out
    # One run-level error, no fabricated per-item failures.
    assert captured.out.count(type(exc).__name__) == 1
    assert "analysis: FAILED" not in captured.out
    assert f"Analysis: FAILED — unavailable ({type(exc).__name__})" in captured.out
    assert str(exc) not in captured.out + captured.err


def test_shared_failure_after_some_items_completed_exposes_no_partial_results(
    monkeypatch, capsys
) -> None:
    """Concurrency means item calls may already have finished when the shared
    error surfaces; those outcomes are unavailable and must not be invented."""
    items = [_item(Source.ARXIV, f"https://a.example/{n}", f"Item {n}") for n in range(3)]
    runners = [_ok_runner(Source.ARXIV, items)]
    monkeypatch.setattr(main_module, "build_runners", lambda: runners)

    completed: list[SourceItem] = []

    async def analyzer(query: str, collected: SourceItemList) -> list[TopicSignalResult]:
        completed.extend(collected[:2])
        raise ProviderConfigurationError("no key")

    monkeypatch.setattr(main_module, "build_analyzer", lambda: analyzer)

    with pytest.raises(SystemExit) as excinfo:
        main_module.main(["custom query"])

    assert excinfo.value.code == 1
    assert len(completed) == 2
    out = capsys.readouterr().out
    assert "Analysis: FAILED — unavailable (ProviderConfigurationError)" in out
    assert "0 analyzed" not in out
    assert "topic:" not in out


def test_total_collection_failure_never_reaches_the_analysis_stage(monkeypatch, capsys) -> None:
    runners = [
        _failing_runner(source)
        for source in (Source.HACKER_NEWS, Source.ARXIV, Source.YOUTUBE, Source.NEWSLETTER)
    ]
    monkeypatch.setattr(main_module, "build_runners", lambda: runners)
    analyzed = _stub_analyzer(monkeypatch)

    with pytest.raises(SystemExit) as excinfo:
        main_module.main(["custom query"])

    assert excinfo.value.code == 1
    assert analyzed == []
    out = capsys.readouterr().out
    assert "Aggregate: FAILED" in out
    assert "Analysis:" not in out


def test_unexpected_analyzer_error_is_not_swallowed(monkeypatch) -> None:
    runners = [_ok_runner(Source.ARXIV, [_item(Source.ARXIV, "https://a.example/1", "item")])]
    monkeypatch.setattr(main_module, "build_runners", lambda: runners)
    _stub_analyzer(monkeypatch, raises=RuntimeError("bug"))

    with pytest.raises(RuntimeError):
        main_module.main(["custom query"])


def test_cancellation_is_not_converted_into_an_exit_code(monkeypatch) -> None:
    runners = [_ok_runner(Source.ARXIV, [_item(Source.ARXIV, "https://a.example/1", "item")])]
    monkeypatch.setattr(main_module, "build_runners", lambda: runners)
    _stub_analyzer(monkeypatch, raises=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        main_module.main(["custom query"])
