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
from pulse.patterns.parallel import RunStatus, SourceRunner, run_sources


def build_runners() -> list[SourceRunner]:
    return [hn_runner(), arxiv_runner(), youtube_runner(), newsletter_runner()]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="PULSE — collect items from Hacker News, ArXiv, YouTube, and newsletters."
    )
    parser.add_argument("query", help="Search query.")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    print("PULSE — collecting from Hacker News, ArXiv, YouTube, newsletters...")
    result = asyncio.run(run_sources(args.query, build_runners()))
    print_run_summary(result)
    if result.status is RunStatus.FAILED:
        raise SystemExit(1)
    print_items(result.items)
    print(f"\nTotal: {len(result.items)} items collected.")


if __name__ == "__main__":
    main()
