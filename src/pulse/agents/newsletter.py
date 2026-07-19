"""Newsletter source agent — direct collector wired into the parallel contract."""

from __future__ import annotations

import functools

from pulse.collectors.newsletter import MAX_RESULTS, fetch_newsletter_items
from pulse.models import Source
from pulse.patterns.parallel import RunStatus, SourceOutput, SourceRunner


def _run_for_parallel(query: str, max_results: int) -> SourceOutput:
    result = fetch_newsletter_items(query, max_results=max_results)
    items = [item for item in result.items if item.source is Source.NEWSLETTER][:max_results]
    if result.failed_feeds:
        return SourceOutput(items=items, status=RunStatus.PARTIAL, error="partial_feed_failure")
    if not items:
        return SourceOutput(items=[], status=RunStatus.PARTIAL, error="no_results")
    return SourceOutput(items=items, status=RunStatus.SUCCESS)


def newsletter_runner(max_results: int = MAX_RESULTS) -> SourceRunner:
    return SourceRunner(
        source=Source.NEWSLETTER,
        run=functools.partial(_run_for_parallel, max_results=max_results),
    )
