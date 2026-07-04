"""PULSE CLI entry point — HN ReAct article collection."""

from __future__ import annotations

import argparse
import sys

from pulse.agents.hn_agent import HN_QUERY, MIN_ARTICLES, run_hn_react
from pulse.display import print_articles, print_trace, warn_if_below_minimum


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="PULSE — collect AI articles from Hacker News.")
    parser.add_argument("query", nargs="?", default=HN_QUERY, help="Search query override.")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    print("PULSE — collecting AI articles from Hacker News...")
    result = run_hn_react(query=args.query)
    print_trace(result.trace)
    print(f"-> {result.stop_reason.value.upper()} (not looping)")
    warn_if_below_minimum(result.items, MIN_ARTICLES)
    print_articles(result.items)
    print(f"\nTotal: {len(result.items)} articles collected.")


if __name__ == "__main__":
    main()
