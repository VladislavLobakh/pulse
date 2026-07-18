"""Parallel fan-out pattern — run independent source runners concurrently.

The engine is source-neutral: each runner is a blocking callable mapping a
query to a `SourceOutput`; the coordinator runs every runner in a worker
thread, converts runner exceptions into failed results, and merges the items
of the surviving results with normalized-URL dedup.

Cancelling the surrounding task stops the wait but cannot interrupt a worker
thread that is already executing — network timeouts remain each source's
responsibility. The `error` fields carry only short codes or exception class
names: exception messages may embed prompts, keys, or provider payloads and
must not reach users or logs.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit

from pulse.logging_config import get_logger
from pulse.models import Source, SourceItem, SourceItemList

logger = get_logger(__name__)


class RunStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class SourceOutput:
    """What a runner reports about its own run; the coordinator adds the rest."""

    items: SourceItemList
    status: RunStatus
    error: str | None = None


# (query) -> SourceOutput. Blocking; the coordinator runs it in a worker thread.
SourceRunFn = Callable[[str], SourceOutput]


@dataclass
class SourceRunner:
    source: Source
    run: SourceRunFn


@dataclass
class SourceRunResult:
    source: Source
    items: SourceItemList
    status: RunStatus
    error: str | None = None
    elapsed_ms: float = 0.0


@dataclass
class ParallelRunResult:
    results: list[SourceRunResult]  # one per runner, in input order
    items: SourceItemList  # combined non-failed items, deduped by normalized URL
    status: RunStatus
    elapsed_ms: float = 0.0


def normalize_url(url: str) -> str:
    """Dedup key: case-insensitive scheme/host, no trailing slash or fragment."""
    stripped = url.strip()
    try:
        parts = urlsplit(stripped)
    except ValueError:
        # A malformed URL must not break aggregation — dedup on the raw string.
        return stripped
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, "")
    )


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


async def _run_one(query: str, runner: SourceRunner) -> SourceRunResult:
    start = time.perf_counter()
    try:
        output = await asyncio.to_thread(runner.run, query)
    except Exception as exc:
        logger.error("Source %s runner failed: %s", runner.source, type(exc).__name__)
        return SourceRunResult(
            source=runner.source,
            items=[],
            status=RunStatus.FAILED,
            error=type(exc).__name__,
            elapsed_ms=_elapsed_ms(start),
        )
    return SourceRunResult(
        source=runner.source,
        items=output.items,
        status=output.status,
        error=output.error,
        elapsed_ms=_elapsed_ms(start),
    )


def _dedup(items: Iterable[SourceItem]) -> SourceItemList:
    seen: set[str] = set()
    unique: SourceItemList = []
    for item in items:
        key = normalize_url(item.url)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        unique.append(item)
    return unique


def _aggregate_status(results: list[SourceRunResult]) -> RunStatus:
    statuses = {result.status for result in results}
    if statuses == {RunStatus.SUCCESS}:
        return RunStatus.SUCCESS
    if statuses == {RunStatus.FAILED}:
        return RunStatus.FAILED
    return RunStatus.PARTIAL


async def run_sources(query: str, runners: Sequence[SourceRunner]) -> ParallelRunResult:
    """Run every configured runner concurrently and combine the surviving items.

    Results keep runner input order regardless of completion order. A runner
    exception becomes a failed per-source result; cancellation propagates.
    """
    if not runners:
        raise ValueError("no source runners configured")
    start = time.perf_counter()
    results = list(await asyncio.gather(*(_run_one(query, runner) for runner in runners)))
    combined = _dedup(
        item for result in results if result.status is not RunStatus.FAILED for item in result.items
    )
    return ParallelRunResult(
        results=results,
        items=combined,
        status=_aggregate_status(results),
        elapsed_ms=_elapsed_ms(start),
    )
