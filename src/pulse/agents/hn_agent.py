"""HN Agent — Day 1: Hacker News via Tavily."""

from __future__ import annotations

from pulse.collectors.tavily import search_articles
from pulse.display import print_articles, warn_if_below_minimum
from pulse.models import ArticleList, Source

HN_QUERY = "AI LLM site:news.ycombinator.com"
MAX_RESULTS = 10
MIN_ARTICLES = 8


def fetch_hn_articles(
    query: str = HN_QUERY,
    max_results: int = MAX_RESULTS,
) -> ArticleList:
    return search_articles(query, Source.HACKER_NEWS, max_results=max_results)


if __name__ == "__main__":
    articles = fetch_hn_articles()
    warn_if_below_minimum(articles, MIN_ARTICLES)
    print_articles(articles)
