"""Tests for pulse.main — the CLI entry point, no real network or LLM calls."""

from __future__ import annotations

import pytest

import pulse.main as main_module
from pulse.models import Source, SourceItem
from pulse.patterns.parallel import RunStatus, SourceOutput, SourceRunner


def _item(source: Source, url: str, title: str) -> SourceItem:
    return SourceItem(title=title, url=url, score=0.9, summary=f"{title} summary.", source=source)


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


def test_build_runners_returns_all_four_sources_in_order() -> None:
    runners = main_module.build_runners()

    assert [r.source for r in runners] == [
        Source.HACKER_NEWS,
        Source.ARXIV,
        Source.YOUTUBE,
        Source.NEWSLETTER,
    ]


def test_main_requires_a_query_argument(capsys) -> None:
    """The query always comes from the caller — there is no built-in default
    topic, so invoking the CLI without one is a usage error."""
    with pytest.raises(SystemExit) as excinfo:
        main_module.main([])

    assert excinfo.value.code == 2
    assert "query" in capsys.readouterr().err


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

    main_module.main(["custom query"])

    assert seen_queries == ["custom query"] * len(runners)
