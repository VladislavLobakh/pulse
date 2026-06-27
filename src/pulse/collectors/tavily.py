"""Tavily search collector — shared across source agents."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from tavily import TavilyClient

from pulse.models import SUMMARY_MAX_CHARS, Article, ArticleList, Source


def parse_tavily_results(raw_results: list[dict], source: Source) -> ArticleList:
    articles = []
    for r in raw_results:
        articles.append(
            Article(
                title=r.get("title") or "Untitled",
                url=r.get("url") or "",
                score=float(r.get("score") or 0.0),
                summary=(r.get("content") or "")[:SUMMARY_MAX_CHARS],
                source=source,
                published_date=r.get("published_date") or "",
            )
        )
    return articles


def search_articles(
    query: str,
    source: Source,
    *,
    max_results: int = 10,
) -> ArticleList:
    load_dotenv()

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY not set — check .env")

    client = TavilyClient(api_key=api_key)
    response = client.search(
        query=query,
        max_results=max_results,
        search_depth="basic",
        include_answer=False,
    )
    return parse_tavily_results(response.get("results", []), source)
