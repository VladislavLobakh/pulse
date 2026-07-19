"""YouTube source agent — direct collector wired into the parallel contract."""

from __future__ import annotations

import functools

from pulse.collectors.youtube import MAX_RESULTS, MAX_TRANSCRIPTS, search_youtube_videos
from pulse.models import Source
from pulse.patterns.parallel import RunStatus, SourceOutput, SourceRunner


def _run_for_parallel(
    query: str,
    max_results: int,
    max_transcripts: int,
) -> SourceOutput:
    result = search_youtube_videos(
        query,
        max_results=max_results,
        max_transcripts=max_transcripts,
    )
    items = [item for item in result.items if item.source is Source.YOUTUBE][:max_results]
    if items and not result.skipped:
        return SourceOutput(items=items, status=RunStatus.SUCCESS)
    if items:
        return SourceOutput(items=items, status=RunStatus.PARTIAL, error="skipped_videos")
    error = "no_transcripts" if result.skipped else "no_results"
    return SourceOutput(items=[], status=RunStatus.PARTIAL, error=error)


def youtube_runner(
    max_results: int = MAX_RESULTS,
    max_transcripts: int = MAX_TRANSCRIPTS,
) -> SourceRunner:
    return SourceRunner(
        source=Source.YOUTUBE,
        run=functools.partial(
            _run_for_parallel,
            max_results=max_results,
            max_transcripts=max_transcripts,
        ),
    )
