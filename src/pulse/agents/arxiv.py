"""ArXiv source agent — direct collector wired into the parallel contract."""

from __future__ import annotations

import functools

from pulse.collectors.arxiv import MAX_PDF_ENRICHMENT, MAX_RESULTS, search_arxiv_papers
from pulse.models import Source
from pulse.patterns.parallel import RunStatus, SourceOutput, SourceRunner


def _run_for_parallel(
    query: str,
    max_results: int,
    pdf_enrichment_limit: int,
) -> SourceOutput:
    items = search_arxiv_papers(
        query,
        max_results=max_results,
        pdf_enrichment_limit=pdf_enrichment_limit,
    )
    items = [item for item in items if item.source is Source.ARXIV][:max_results]
    if not items:
        return SourceOutput(items=[], status=RunStatus.PARTIAL, error="no_results")
    return SourceOutput(items=items, status=RunStatus.SUCCESS)


def arxiv_runner(
    max_results: int = MAX_RESULTS,
    pdf_enrichment_limit: int = MAX_PDF_ENRICHMENT,
) -> SourceRunner:
    return SourceRunner(
        source=Source.ARXIV,
        run=functools.partial(
            _run_for_parallel,
            max_results=max_results,
            pdf_enrichment_limit=pdf_enrichment_limit,
        ),
    )
