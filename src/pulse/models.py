"""Shared domain models for PULSE source items and sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field


class Source(StrEnum):
    HACKER_NEWS = "hacker_news"
    ARXIV = "arxiv"
    YOUTUBE = "youtube"
    NEWSLETTER = "newsletter"
    TWITTER = "twitter"


@dataclass
class SourceItem:
    title: str
    url: str
    score: float  # normalized relevance/quality signal, 0-1
    summary: str  # short source-provided or generated snippet
    source: Source
    published_date: str = ""


SourceItemList = list[SourceItem]


# --- LLM output contracts (Pydantic — Instructor requires Pydantic) ---


class ReasonDecision(BaseModel):
    thought: str = Field(
        description="Brief internal reasoning for why this query should surface "
        "better results than the current one."
    )
    query: str = Field(
        description="The next search query to try, incorporating the "
        "improvement identified in `thought`."
    )


class SourceBatchScore(BaseModel):
    relevance: float = Field(
        ge=0,
        le=1,
        description="How closely the batch matches the current search intent "
        "(0 = off-topic, 1 = squarely on-topic).",
    )
    novelty: float = Field(
        ge=0,
        le=1,
        description="How much new information the batch adds beyond content "
        "already known or previously seen (0 = stale/repeat, 1 = fresh).",
    )
    quality: float = Field(
        ge=0,
        le=1,
        description="Editorial/technical quality of the items themselves "
        "(0 = low-effort or spam, 1 = well-sourced and substantive).",
    )

    @property
    def overall(self) -> float:
        return (self.relevance + self.novelty + self.quality) / 3


# --- Run result + trace (returned to callers, not LLM outputs) ---


class StopReason(StrEnum):
    SCORE_THRESHOLD = "score_threshold"
    MAX_ITERATIONS = "max_iterations"
    NO_RESULTS = "no_results"
    ERROR = "error"


class TraceKind(StrEnum):
    REASON = "reason"
    ACT = "act"
    OBSERVE = "observe"


@dataclass
class TraceEvent:
    kind: TraceKind
    message: str
    query: str | None = None
    result_count: int | None = None
    score: float | None = None


@dataclass
class ReActResult:
    items: SourceItemList
    stop_reason: StopReason
    trace: list[TraceEvent] = field(default_factory=list)
    best_score: float = 0.0
    iterations: int = 0
