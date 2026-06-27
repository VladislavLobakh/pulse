"""Shared domain models for PULSE articles and sources."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

SUMMARY_MAX_CHARS = 500


class Source(StrEnum):
    HACKER_NEWS = "hacker_news"
    ARXIV = "arxiv"
    YOUTUBE = "youtube"
    NEWSLETTER = "newsletter"
    TWITTER = "twitter"


@dataclass
class Article:
    title: str
    url: str
    score: float  # Tavily relevance 0-1, NOT vote count
    summary: str  # Tavily "content" truncated to SUMMARY_MAX_CHARS
    source: Source
    published_date: str = ""


ArticleList = list[Article]
