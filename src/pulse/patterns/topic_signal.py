"""Structured source-item analyzer — per-item extraction over an ordered list
of `SourceItem`s, one `TopicSignal` (or a safe failure) per item.

Each item is judged only by its own content, with no other item or prior
history available — the contract has no novelty/trend field for that reason.
Concurrency is bounded via a semaphore and run off the event loop through
`asyncio.to_thread` + `asyncio.gather`, same shape as `patterns.parallel`;
cancelling the caller's task stops the wait but can't interrupt an in-flight
worker thread. Only `ModelsExhaustedError` isolates as a per-item failure;
every other exception aborts the batch (see `_analyze_one`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from pulse.llm import ModelsExhaustedError
from pulse.logging_config import get_logger
from pulse.models import SourceItem, SourceItemList

logger = get_logger(__name__)

DEFAULT_MAX_CONCURRENCY = 5


class EventType(StrEnum):
    RELEASE = "release"
    RESEARCH = "research"
    TUTORIAL = "tutorial"
    DISCUSSION = "discussion"
    RECAP = "recap"
    OTHER = "other"
    UNKNOWN = "unknown"


# --- LLM output contract (Pydantic — Instructor requires Pydantic) ---


class TopicSignal(BaseModel):
    # min_length=1 alone accepts whitespace-only strings (" " has len 1);
    # stripping first makes the length check mean "has real content".
    model_config = ConfigDict(str_strip_whitespace=True)

    topic: str = Field(
        min_length=1,
        description="The specific subject, technology, product, or concept this item is about.",
    )
    event_type: EventType = Field(
        description="What kind of event this item represents, judged only "
        "from this item's own content. Use RECAP when the item's own wording "
        "reads as a rehash of something already announced (e.g. 'as "
        "previously announced...') — never infer repetition by comparing "
        "against other items, since none are available. Use UNKNOWN when the "
        "item's content does not give enough evidence to categorize it: if "
        "the title and summary are generic boilerplate such as 'update', "
        "'minor fixes', 'news', or 'thoughts?', with no named subject and no "
        "stated change, the correct answer is UNKNOWN. Picking a specific "
        "category from a generic word is a guess, not a judgment — never "
        "assume RELEASE just because the item mentions an update or a fix."
    )
    key_change: str = Field(
        min_length=1,
        description="Concretely, what changed or was announced, grounded "
        "only in this item's content.",
    )
    relevance: float = Field(
        ge=0,
        le=1,
        description="How relevant this item is to the ORIGINAL user query "
        "(0 = off-topic, 1 = squarely on-topic). Judge this independently of "
        "confidence: an off-topic item can still be extracted with high "
        "confidence.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Confidence in the accuracy of this extraction given the "
        "item's content (0 = mostly guessing due to sparse or ambiguous "
        "content, 1 = clearly supported). Score by how much the item actually "
        "says, not by how fluent your own answer reads: when the content is "
        "generic boilerplate with no named subject and no stated change, stay "
        "below 0.5, and reserve scores above 0.8 for items whose own text "
        "states the subject and the change outright.",
    )
    evidence: str = Field(
        min_length=1,
        description="Short explanation grounded in the supplied item — quote "
        "or closely paraphrase the item, never outside knowledge.",
    )


# --- Run result (returned to callers, not an LLM output) ---


class AnalysisStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class AnalysisRunStatus(StrEnum):
    """Whole-run outcome. SKIPPED means the stage never ran at all, which is
    not the same as having run and failed."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TopicSignalResult:
    item: SourceItem
    status: AnalysisStatus
    signal: TopicSignal | None = None
    error: str | None = None


def _aggregate_status(results: list[TopicSignalResult]) -> AnalysisRunStatus:
    statuses = {result.status for result in results}
    # Empty means the analyzer ran over an empty item list, which succeeded
    # trivially; the set-based checks below would call it PARTIAL.
    if not statuses or statuses == {AnalysisStatus.SUCCESS}:
        return AnalysisRunStatus.SUCCESS
    if statuses == {AnalysisStatus.FAILED}:
        return AnalysisRunStatus.FAILED
    return AnalysisRunStatus.PARTIAL


@dataclass
class AnalysisRunResult:
    """Whole-run analysis outcome, the analyzer's counterpart to
    `ParallelRunResult`. Build it through the three constructors below rather
    than directly: they are the only shapes a run can end in, and they keep
    `status` from disagreeing with `results`.
    """

    results: list[TopicSignalResult] | None  # None when no complete set was returned
    status: AnalysisRunStatus
    error: str | None = None

    @property
    def analyzed_count(self) -> int:
        return sum(1 for r in self.results or () if r.status is AnalysisStatus.SUCCESS)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results or () if r.status is AnalysisStatus.FAILED)

    @classmethod
    def completed(cls, results: list[TopicSignalResult]) -> AnalysisRunResult:
        return cls(results=results, status=_aggregate_status(results))

    @classmethod
    def aborted(cls, error: str) -> AnalysisRunResult:
        """A shared failure stopped the batch, so no per-item outcome is
        trustworthy — not even for items whose calls had already returned."""
        return cls(results=None, status=AnalysisRunStatus.FAILED, error=error)

    @classmethod
    def skipped(cls) -> AnalysisRunResult:
        return cls(results=None, status=AnalysisRunStatus.SKIPPED)


@dataclass
class _AbortSignal:
    """Shared across one batch's tasks; `asyncio.gather` doesn't cancel
    siblings when one raises, so a fail-fast error must set this itself."""

    triggered: bool = False


# (messages=..., response_model=...) -> BaseModel; blocking, run in a worker
# thread — normally `complete_structured` bound via `functools.partial`, as in `agents/hn.py`.
StructuredLLMFn = Callable[..., BaseModel]


def _build_messages(query: str, item: SourceItem) -> list[dict]:
    system = (
        "You extract a single, grounded topic signal from one source item "
        "for a research assistant. Judge this item only by its own content — "
        "you have no access to other items or prior history, so never infer "
        "repetition or trends by comparison; use the RECAP and UNKNOWN "
        "event_type values as described for what this one item's own wording "
        "supports. A thin item is a valid outcome, not a problem to solve: "
        "when the content barely says anything, report that honestly through "
        "UNKNOWN and a low confidence rather than inventing a specific "
        "category the text does not support."
    )
    user = (
        f"Original query: {query!r}\n\n"
        f"Source: {item.source.value}\n"
        f"Title: {item.title}\n"
        f"Published: {item.published_date or 'unknown'}\n"
        f"Summary: {item.summary}\n"
        f"URL: {item.url}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def _analyze_one(
    semaphore: asyncio.Semaphore,
    query: str,
    item: SourceItem,
    analyze_llm: StructuredLLMFn,
    abort: _AbortSignal,
) -> TopicSignalResult:
    async with semaphore:
        if abort.triggered:
            # Set synchronously by a sibling before any other task can
            # observe it — no `await` runs between that write and this check.
            raise asyncio.CancelledError("batch aborted by a sibling's error")
        messages = _build_messages(query, item)
        try:
            signal = await asyncio.to_thread(
                analyze_llm, messages=messages, response_model=TopicSignal
            )
        except ModelsExhaustedError as exc:
            logger.warning("Item analysis exhausted for %r: %s", item.url, exc)
            return TopicSignalResult(
                item=item, status=AnalysisStatus.FAILED, error=type(exc).__name__
            )
        except BaseException:
            # Anything else — FAIL_FAST_ERRORS or an unclassified bug —
            # aborts the batch too, not only the named fail-fast classes.
            abort.triggered = True
            raise
    return TopicSignalResult(item=item, status=AnalysisStatus.SUCCESS, signal=signal)


async def analyze_items(
    query: str,
    items: SourceItemList,
    analyze_llm: StructuredLLMFn,
    *,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
) -> list[TopicSignalResult]:
    """Analyze every item at most once, one result per item, input order
    preserved regardless of completion order. See module docstring for the
    fail-fast/isolate error split.
    """
    if max_concurrency < 1:
        raise ValueError(f"max_concurrency must be >= 1, got {max_concurrency}")
    if not items:
        return []
    semaphore = asyncio.Semaphore(max_concurrency)
    abort = _AbortSignal()
    return list(
        await asyncio.gather(
            *(_analyze_one(semaphore, query, item, analyze_llm, abort) for item in items)
        )
    )
