"""CLI output helpers."""

from __future__ import annotations

from pulse.models import SourceItemList
from pulse.patterns.parallel import ParallelRunResult, SourceRunResult


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


def print_items(items: SourceItemList) -> None:
    print(f"\n=== PULSE — {len(items)} items ===\n")
    for i, item in enumerate(items, 1):
        print(f"{i}. {item.title}")
        print(f"   source: {item.source}")
        print(f"   url:   {item.url}")
        print(f"   score: {item.score:.3f}")
        if item.published_date:
            print(f"   date:  {item.published_date}")
        print(f"   summary: {item.summary}")
        print("---")
