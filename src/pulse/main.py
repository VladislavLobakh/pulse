"""PULSE CLI entry point — parallel multi-source article collection."""

from __future__ import annotations

import argparse
import asyncio
import sys

from pulse.agents.arxiv import arxiv_runner
from pulse.agents.hn import hn_runner
from pulse.agents.newsletter import newsletter_runner
from pulse.agents.youtube import youtube_runner
from pulse.display import print_items, print_run_summary
from pulse.patterns.parallel import ParallelRunResult, RunStatus, SourceRunner, run_sources
from pulse.workflows.research import (
    Coordinator,
    InvalidQueryError,
    PulseOutput,
    build_research_graph,
)


def build_runners() -> list[SourceRunner]:
    return [hn_runner(), arxiv_runner(), youtube_runner(), newsletter_runner()]


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
    graph = build_research_graph(_production_coordinator(build_runners()))
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
    print_items(result.items)
    print(f"\nTotal: {len(result.items)} items collected.")


if __name__ == "__main__":
    main()
