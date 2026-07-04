"""CLI output helpers."""

from __future__ import annotations

import sys

from pulse.agents.react_loop import _step_suffix
from pulse.models import SourceItemList, TraceEvent


def print_trace(trace: list[TraceEvent]) -> None:
    print("\n=== Reason / Act / Observe trace ===\n")
    for event in trace:
        print(f"{event.kind.capitalize()}: {event.message}{_step_suffix(event)}")
    print()


def warn_if_below_minimum(items: SourceItemList, min_count: int) -> None:
    if len(items) < min_count:
        print(
            f"WARNING: only {len(items)} articles returned (expected {min_count}+)",
            file=sys.stderr,
        )


def print_articles(items: SourceItemList) -> None:
    print(f"\n=== PULSE — {len(items)} articles ===\n")
    for i, item in enumerate(items, 1):
        print(f"{i}. {item.title}")
        print(f"   source: {item.source}")
        print(f"   url:   {item.url}")
        print(f"   score: {item.score:.3f}")
        if item.published_date:
            print(f"   date:  {item.published_date}")
        print(f"   summary: {item.summary}")
        print("---")
