"""PULSE CLI entry point — parallel multi-source article collection."""

from __future__ import annotations

import argparse
import asyncio
import functools
import sys

from pulse.agents.arxiv import arxiv_runner
from pulse.agents.hn import hn_runner
from pulse.agents.newsletter import newsletter_runner
from pulse.agents.youtube import youtube_runner
from pulse.display import print_analysis_summary, print_items, print_run_summary
from pulse.llm import complete_structured
from pulse.models import SourceItemList
from pulse.patterns.parallel import ParallelRunResult, RunStatus, SourceRunner, run_sources
from pulse.patterns.topic_signal import (
    AnalysisRunStatus,
    StructuredLLMFn,
    TopicSignalResult,
    analyze_items,
)
from pulse.workflows.research import (
    Analyzer,
    Coordinator,
    InvalidQueryError,
    PulseOutput,
    build_research_graph,
)

# Cross-source per-item extraction: one structured signal per collected item.
# Chain and sampling live here as the single source of truth the eval imports.
ANALYSIS_MODELS = [
    "openrouter/qwen/qwen3.5-flash-02-23",
    "openrouter/google/gemini-2.5-flash-lite",
]
LLM_TEMPERATURE = 0.1
LLM_MAX_TOKENS = 700


def build_runners() -> list[SourceRunner]:
    return [hn_runner(), arxiv_runner(), youtube_runner(), newsletter_runner()]


def _analyze_llm() -> StructuredLLMFn:
    return functools.partial(
        complete_structured,
        models=ANALYSIS_MODELS,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
    )


def build_analyzer() -> Analyzer:
    analyze_llm = _analyze_llm()

    async def analyzer(query: str, items: SourceItemList) -> list[TopicSignalResult]:
        return await analyze_items(query, items, analyze_llm)

    return analyzer


def _production_coordinator(runners: list[SourceRunner]) -> Coordinator:
    async def coordinator(query: str) -> ParallelRunResult:
        return await run_sources(query, runners)

    return coordinator


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="PULSE — collect items from Hacker News, ArXiv, YouTube, and newsletters."
    )
    parser.add_argument("query", help="Search query.")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    print("PULSE — collecting from Hacker News, ArXiv, YouTube, newsletters...")
    graph = build_research_graph(
        _production_coordinator(build_runners()),
        build_analyzer(),
    )
    try:
        output: PulseOutput = asyncio.run(graph.ainvoke({"query": args.query}))
    except InvalidQueryError as exc:
        # Raised by initialize_state before the coordinator runs.
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None

    result = output["result"]
    print_run_summary(result)
    if result.status is RunStatus.FAILED:
        raise SystemExit(1)
    analysis = output["analysis"]
    print_items(result.items, analysis.results)
    print(f"\nTotal: {len(result.items)} items collected.")
    print_analysis_summary(analysis)
    if analysis.status is AnalysisRunStatus.FAILED:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
