"""Shared domain models for PULSE source items and sources.

Pattern-specific LLM contracts and run results live with their pattern
(e.g. `pulse.patterns.react`); this module holds only what every layer shares.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Source(StrEnum):
    HACKER_NEWS = "hacker_news"
    ARXIV = "arxiv"
    YOUTUBE = "youtube"
    NEWSLETTER = "newsletter"


@dataclass
class SourceItem:
    title: str
    url: str
    score: float  # normalized relevance/quality signal, 0-1
    summary: str  # short source-provided or generated snippet
    source: Source
    published_date: str = ""


SourceItemList = list[SourceItem]
