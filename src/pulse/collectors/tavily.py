"""Tavily search and extraction collector — shared across source agents."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from tavily import TavilyClient

from pulse.logging_config import get_logger
from pulse.models import Source, SourceItem, SourceItemList

logger = get_logger(__name__)

SUMMARY_MAX_CHARS = 500
EXTRACT_TIMEOUT_SECONDS = 20.0


def parse_tavily_results(raw_results: list[dict], source: Source) -> SourceItemList:
    items = []
    for r in raw_results:
        items.append(
            # score: Tavily relevance.
            # summary: Tavily "content", truncated to SUMMARY_MAX_CHARS.
            SourceItem(
                title=r.get("title") or "Untitled",
                url=r.get("url") or "",
                score=float(r.get("score") or 0.0),
                summary=(r.get("content") or "")[:SUMMARY_MAX_CHARS],
                source=source,
                published_date=r.get("published_date") or "",
            )
        )
    return items


def search_articles(
    query: str,
    source: Source,
    *,
    max_results: int = 10,
    include_domains: list[str] | None = None,
) -> SourceItemList:
    load_dotenv()

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY not set — check .env")

    logger.debug("Tavily search query=%r source=%s max_results=%d", query, source, max_results)
    client = TavilyClient(api_key=api_key)
    response = client.search(
        query=query,
        max_results=max_results,
        search_depth="basic",
        include_answer=False,
        include_domains=include_domains,
    )
    raw_results = response.get("results", [])
    logger.debug("Tavily search query=%r returned %d raw results", query, len(raw_results))
    return parse_tavily_results(raw_results, source)


def extract_content(
    urls: list[str],
    *,
    query: str,
    chunks_per_source: int = 3,
    timeout: float = EXTRACT_TIMEOUT_SECONDS,
) -> dict[str, str]:
    """Extract query-focused text, omitting failed or malformed results."""
    if not urls:
        return {}

    load_dotenv()
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY not set — check .env")

    client = TavilyClient(api_key=api_key)
    response = client.extract(
        urls=urls,
        query=query,
        chunks_per_source=chunks_per_source,
        format="text",
        extract_depth="advanced",
        timeout=timeout,
    )
    raw_results = response.get("results", [])
    if not isinstance(raw_results, list):
        return {}

    extracted: dict[str, str] = {}
    for result in raw_results:
        if not isinstance(result, dict):
            continue
        url = result.get("url")
        raw_content = result.get("raw_content")
        if isinstance(url, str) and url and isinstance(raw_content, str) and raw_content:
            extracted[url] = raw_content
    return extracted
