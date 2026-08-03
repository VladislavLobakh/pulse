"""CLI output helpers."""

from __future__ import annotations

from pulse.models import SourceItemList
from pulse.patterns.parallel import ParallelRunResult, SourceRunResult
from pulse.patterns.topic_signal import AnalysisRunResult, AnalysisStatus, TopicSignalResult


def _format_elapsed(elapsed_ms: float) -> str:
    return f"{elapsed_ms / 1000:.1f}s"


def _source_line(result: SourceRunResult) -> str:
    line = (
        f"{result.source.value:<12} {result.status.value.upper():<8}"
        f" {len(result.items):>3} items  {_format_elapsed(result.elapsed_ms):>7}"
    )
    if result.error:
        line += f"  ({result.error})"
    return line


def print_run_summary(result: ParallelRunResult) -> None:
    print("\n=== PULSE — source summary ===\n")
    for source_result in result.results:
        print(_source_line(source_result))
    print(
        f"\nAggregate: {result.status.value.upper()} — "
        f"{len(result.items)} unique items in {_format_elapsed(result.elapsed_ms)}"
    )


def _require_aligned(items: SourceItemList, analysis: list[TopicSignalResult]) -> None:
    """Analysis results are positional — a mismatch is a caller bug, and
    rendering around it would attach one item's signal to another."""
    if len(analysis) != len(items):
        raise ValueError(f"analysis has {len(analysis)} results for {len(items)} items")
    for position, (item, result) in enumerate(zip(items, analysis, strict=True)):
        if result.item != item:
            raise ValueError(f"analysis result {position} does not match its item")


def _print_analysis(result: TopicSignalResult) -> None:
    if result.status is AnalysisStatus.FAILED or result.signal is None:
        # Only the stored code — provider messages may embed keys or prompts.
        print(f"   analysis: FAILED ({result.error})")
        return
    signal = result.signal
    print(f"   topic: {signal.topic} ({signal.event_type.value})")
    print(f"   change: {signal.key_change}")
    print(f"   signal: relevance {signal.relevance:.2f} · confidence {signal.confidence:.2f}")
    print(f"   evidence: {signal.evidence}")


def print_items(items: SourceItemList, analysis: list[TopicSignalResult] | None = None) -> None:
    if analysis is not None:
        _require_aligned(items, analysis)
    print(f"\n=== PULSE — {len(items)} items ===\n")
    for i, item in enumerate(items, 1):
        print(f"{i}. {item.title}")
        print(f"   source: {item.source}")
        print(f"   url:   {item.url}")
        print(f"   score: {item.score:.3f}")
        if item.published_date:
            print(f"   date:  {item.published_date}")
        print(f"   summary: {item.summary}")
        if analysis is not None:
            _print_analysis(analysis[i - 1])
        print("---")


def print_analysis_summary(analysis: AnalysisRunResult) -> None:
    line = f"\nAnalysis: {analysis.status.value.upper()} — "
    if analysis.error:
        print(f"{line}unavailable ({analysis.error})")
        return
    print(f"{line}{analysis.analyzed_count} analyzed, {analysis.failed_count} failed")
