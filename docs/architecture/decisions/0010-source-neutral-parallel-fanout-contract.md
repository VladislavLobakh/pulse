# 10. Source-neutral parallel fan-out contract

Date: 2026-07-18

## Status

Accepted

## Context

PULSE is about to grow from one source (HN) to several (ArXiv, YouTube,
newsletters). The daily-digest target flow already names `asyncio.gather()` as
the fan-out primitive, but the codebase was fully synchronous and had no
shared result contract: `main.py` called `run_hn_react` directly, and any
exception crashed the whole run. Before sources multiply we need a concurrency
layer that isolates per-source failures, measures each run, and merges items —
without embedding source knowledge in the coordinator.

## Decision

Add `patterns/parallel.py` — a source-neutral fan-out engine with explicit
dataclass contracts (run results, not LLM outputs, so no Pydantic):

- A runner is `SourceRunner(source, run)` where `run: (query) -> SourceOutput`.
  `SourceOutput(items, status, error)` is reported by the source itself, so a
  per-source `PARTIAL` is genuinely reachable; the coordinator adds only what
  it alone knows (`source`, `elapsed_ms`) to form `SourceRunResult`.
- Runners are blocking sync callables executed via `asyncio.to_thread` inside
  `asyncio.gather` — chosen over `TaskGroup` for input-order results and
  minimal bookkeeping (wrappers never raise, so sibling cancellation adds
  nothing). Cancelling the surrounding task cannot interrupt a running worker
  thread; network timeouts remain each source's responsibility. Async-native
  runners are a future additive extension.
- A runner exception becomes a `FAILED` result (`except Exception` only, so
  cancellation propagates). User-facing `error` is a short code or exception
  class name — never the exception message, which may embed prompts, keys, or
  provider payloads. Logging follows the same rule: no `logger.exception()` /
  tracebacks, only source + exception class name.
- Aggregate status: all `FAILED` -> `FAILED`; all `SUCCESS` -> `SUCCESS`;
  anything else -> `PARTIAL`. Combined items come from all non-`FAILED`
  results, deduped by normalized URL (case-insensitive scheme/host, no
  trailing slash or fragment; first occurrence in runner input order wins;
  empty URLs never deduped; malformed URLs fall back to the raw string
  instead of raising). An empty runner collection is a configuration error
  (`ValueError`), not a vacuous success.
- The HN agent joins via a thin adapter (`agents/hn.py hn_runner`) that maps
  `ReActResult` to `SourceOutput`: `SUCCESS` only when the loop stopped via
  `SCORE_THRESHOLD` with at least `min(MIN_ARTICLES, max_results)` items;
  otherwise `PARTIAL` with a safe reason code (`below_min_articles`,
  `max_iterations`, `no_results`).
- No new dev dependencies: tests drive the async API with `asyncio.run` and
  prove concurrency with `threading.Barrier`/`Event` (timeouts as failure
  guards, no sleeps).

## Consequences

- A new source joins by writing one adapter function returning a
  `SourceRunner`; the coordinator stays source-blind.
- Only the fan-out foundation and the HN adapter are Implemented. CLI wiring,
  LangGraph orchestration, and real ArXiv/YouTube/newsletter integrations stay
  Planned.
- Per-source `PARTIAL` semantics are owned by each source's adapter; the
  coordinator only preserves them.
- Error observability is deliberately reduced to codes/class names at this
  boundary; detailed diagnosis relies on source-level logging.

## Alternatives Considered

- `asyncio.TaskGroup`: viable, but `gather` returns results in input order
  with less bookkeeping; TaskGroup's sibling-cancellation adds nothing when
  per-runner wrappers never raise.
- `gather(return_exceptions=True)`: mixes exceptions into the result list and
  loses the typed per-source contract.
- Async-native runner contract with a sync adapter helper: no async producers
  exist anywhere in the codebase yet; would complicate the contract for no
  consumer.
- Raw `ThreadPoolExecutor` without asyncio: the target architecture
  (daily-digest orchestrator) is event-loop-native.
- Adding `pytest-asyncio`: unnecessary — `asyncio.run` inside sync tests
  covers everything deterministically.

## Related

- Architecture: [../../architecture.md](../../architecture.md)
- Flow: [../flows/parallel-collect.mmd](../flows/parallel-collect.mmd)
- ADR 6: generic ReAct loop engine separate from source agents
- ADR 9: package-by-pattern module structure
