"""PULSE CLI entry point — HN article collection."""

from __future__ import annotations

from pulse.agents.hn_agent import MIN_ARTICLES, fetch_hn_articles
from pulse.display import print_articles, warn_if_below_minimum
from pulse.models import ArticleList


def main() -> None:
    print("PULSE — collecting AI articles from Hacker News...")
    articles: ArticleList = fetch_hn_articles()
    warn_if_below_minimum(articles, MIN_ARTICLES)
    print_articles(articles)
    print(f"\nTotal: {len(articles)} articles collected.")


if __name__ == "__main__":
    main()
