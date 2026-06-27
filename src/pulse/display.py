"""CLI output helpers."""

from __future__ import annotations

import sys

from pulse.models import ArticleList


def warn_if_below_minimum(articles: ArticleList, min_count: int) -> None:
    if len(articles) < min_count:
        print(
            f"WARNING: only {len(articles)} articles returned (expected {min_count}+)",
            file=sys.stderr,
        )


def print_articles(articles: ArticleList) -> None:
    print(f"\n=== PULSE — {len(articles)} articles ===\n")
    for i, article in enumerate(articles, 1):
        print(f"{i}. {article.title}")
        print(f"   source: {article.source}")
        print(f"   url:   {article.url}")
        print(f"   score: {article.score:.3f}")
        if article.published_date:
            print(f"   date:  {article.published_date}")
        print(f"   summary: {article.summary}")
        print("---")
