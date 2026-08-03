# 18. Research workflow analyzes collected items

Date: 2026-08-03

## Status

Accepted

## Context

ADR 17 defined the `topic_signal` extraction contract but left the engine
dormant: no agent bound `analyze_llm`, no workflow called `analyze_items`, and
extraction quality was unverified against a live model. The CLI therefore
collected items and reported nothing about them.

Wiring the analyzer into the research graph raises questions the collection
stage never had to answer. Collection has one aggregate status; analysis is a
second, independent stage that can fail on its own while collection succeeded,
or never run at all because collection collapsed. ADR 17's error split makes
those two failure modes structurally different: `ModelsExhaustedError` isolates
per item and still yields a complete ordered result list, while a shared
account/config error makes `analyze_items` raise, so no result list exists.

## Decision

- Add an `analyze_items` node between the status route and `finalize_results`.
  `FAILED` collection routes straight to `finalize_failure`, so the analyzer is
  never called. The graph stays acyclic and still carries no `recursion_limit`.
- `build_research_graph(coordinator, analyzer)` takes the analyzer as a second
  required injected dependency, the same DI shape as the coordinator (ADR 6).
  Optional injection was rejected: it invents a "collection succeeded, analysis
  never configured" state with no honest value in the status vocabulary.
- The node passes `parallel_result.items` — already ordered and URL-deduped by
  `patterns.parallel` — to the analyzer exactly once. No refetch of item URLs
  and no second analysis path exist.
- `AnalysisRunStatus` has four members: `SUCCESS`, `PARTIAL`, `FAILED`, and
  `SKIPPED`. `SKIPPED` is first-class rather than folded into `FAILED` because
  a stage that never ran is not a stage that failed, and a future digest
  workflow must be able to tell "analysis rejected these items" from "analysis
  never happened".
- The run's analysis outcome is one `AnalysisRunResult` dataclass, the
  analyzer's counterpart to `ParallelRunResult`, so `PulseOutput` stays two
  symmetric fields (`result`, `analysis`) rather than a flat bag of five. It
  carries `results`, `status`, and `error`; `analyzed_count`/`failed_count`
  are properties derived from `results`, so they are part of the public
  contract yet cannot drift from it.
- Three classmethods — `completed(results)`, `aborted(error)`, `skipped()` —
  are the only ways a run ends, and `completed` derives `status` itself, so a
  status that disagrees with its results is not constructible in normal use.
- `AnalysisRunResult.results` is `list[TopicSignalResult] | None` with three
  distinct meanings: `None` = no complete, trustworthy per-item result set was
  returned (skipped, or the analyzer raised); `[]` = ran to completion over
  zero collected items; non-empty = one entry per item, in item order.
- The node catches only `pulse.llm.FAIL_FAST_ERRORS` — the existing public
  tuple, not a re-listed copy — and records it through
  `AnalysisRunResult.aborted(...)`, whose `error` holds the exception class
  name and nothing else. It never fabricates
  per-item failures from a shared error. Because analysis is concurrent, some
  item calls may already have started or completed when the shared error
  surfaced; those outcomes are unavailable and are deliberately not recovered.
  `analyzed_count`/`failed_count` therefore count exposed per-item results, not
  provider calls issued.
- Everything outside that tuple — unclassified bugs, `asyncio.CancelledError`,
  `KeyboardInterrupt` — propagates untouched. No `KeyboardInterrupt` handler
  was added to the CLI: propagate-and-traceback already satisfies "not
  swallowed", and catching it would be the swallowing that must not happen.
- CLI exit codes: 2 invalid query, 1 total collection failure (unchanged — no
  item listing, no analysis section), 0 for analysis `SUCCESS` and `PARTIAL`
  (mirroring partial collection), 1 for analysis `FAILED` with the collection
  summary and the full item listing preserved.
- Presentation stays in `display.py`; no workflow node prints. `print_items`
  validates that analysis results are positionally aligned with the items and
  raises on a length or order mismatch rather than rendering around it.
- No C4 container change: this is an in-process wiring change inside the
  already-`Implemented` Agent Runtime container (architecture update rule 3).

## Consequences

- Supersedes ADR 17's dormancy statement in full: an agent now binds
  `analyze_llm` (`main.build_analyzer`), a workflow now calls `analyze_items`,
  and `docs/patterns.md` gains the row that ADR 17 deferred until wiring
  landed. ADR 17's file is left unedited, following ADR 16's precedent.
- Partially discharges ADR 8's deferred item 2 ("no per-item verification"):
  collected items now carry an individual grounded judgment rather than only a
  batch-level score.
- Every CLI run now costs LLM calls proportional to collected items. Analyzed
  items are bounded by the four sources' `MAX_RESULTS` (~40 after URL dedup),
  but provider requests are higher, since the gateway retries transient errors
  in place (tenacity `stop_after_attempt(3)`), lets Instructor reask once
  (`max_retries=1`), and falls back across the chain:

  ```
  provider_requests ≤ analyzed_items × Σ over ANALYSIS_MODELS of
                      (transient retries × reask attempts)
  typical case      = analyzed_items          (one request per item)
  ```

  With the validated two-model chain that is a worst case well above the item
  count; concurrency is capped at `DEFAULT_MAX_CONCURRENCY = 5` behind a 30s
  per-request timeout. There is deliberately no `--no-analysis` flag: a runtime
  skip would be a second production path with its own untested states.
- Analysis progress is invisible during a run — `agents/hn.py`'s `PULSE_VERBOSE`
  live printer has no analyzer analogue, and none was added. `PULSE_LOG_LEVEL=DEBUG`
  surfaces per-call gateway logs for anyone who needs them.

## Alternatives Considered

- Fabricate one `TopicSignalResult(status=FAILED)` per item on a shared error:
  rejected — it reinstates the "isolate every error per item" design ADR 17
  already rejected, one layer up, and makes `failed_count == len(items)`
  indistinguishable from every item genuinely exhausting its model chain.
- Fold `SKIPPED` into `FAILED`: rejected — it reports a stage that never ran as
  a failed stage, and a consumer branching on the status cannot recover the
  difference.
- Omit the analysis keys from `finalize_failure` so absence encodes "never
  ran": rejected — it forces `.get()` on every consumer and loosens the typed
  output guarantee ADR 15 built.
- Spread `analysis`, `analysis_status`, the two counts, and `analysis_error`
  as five sibling keys of `PulseOutput` (first implementation): rejected on
  review — it was asymmetric with the single `ParallelRunResult` on the
  collection side, let the counts drift from the results they summarize, and
  pushed the legal-state table into comments no code enforced.
- A full sum type (`Skipped | Completed | Aborted`) making illegal states
  unrepresentable: rejected — it is the most correct model, but a union of
  dataclasses plus `match` at every consumer is heavier than this codebase's
  plain-dataclass style, and the three constructors close most of the gap.
- Reuse `RunStatus` from `patterns.parallel` for the run-level analysis status:
  rejected — it couples two sibling pattern engines, and the aggregation rules
  genuinely differ, since an empty analysis is a `SUCCESS` here but
  `_aggregate_status([])` returns `PARTIAL`.

## Related

- Architecture: [../../architecture.md](../../architecture.md)
- Pattern table: [../../patterns.md](../../patterns.md)
- Flow: [../flows/research-workflow.mmd](../flows/research-workflow.mmd)
- Code: `src/pulse/workflows/research.py`, `src/pulse/patterns/topic_signal.py`,
  `src/pulse/display.py`, `src/pulse/main.py`
- ADR 6: generic ReAct loop engine separate from source agents
- ADR 8: intent contract and eval-driven model selection
- ADR 15: research workflow graph over the parallel coordinator
- ADR 16: CLI invokes the research workflow graph
- ADR 17: topic-signal single-item extraction contract (superseded dormancy
  statement about the engine having no wired-in caller)
