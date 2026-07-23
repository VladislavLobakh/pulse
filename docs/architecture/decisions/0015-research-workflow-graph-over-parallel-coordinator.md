# 15. Research workflow graph over the parallel coordinator

Date: 2026-07-23

## Status

Accepted

## Context

The parallel coordinator (ADR 10, `patterns/parallel.py`) runs the four sources
concurrently and returns a `ParallelRunResult`, and the CLI (ADR 14) calls it
directly. There is no orchestration layer above the coordinator: nothing owns
query validation, stage ordering, or routing on the aggregate status, and there
is no typed public entry contract for a "run the research" step that later stages
(digest, LinkedIn drafts) can build on.

We need that core now, but without pulling in the larger planned orchestrator —
the LLM planning loop, adaptive source selection, and RAG routing sketched in
`flows/langgraph-orchestrator.mmd` are explicitly out of scope here.

## Decision

- Add a `src/pulse/workflows/` package for product workflows that compose
  patterns + capabilities, distinct from `patterns/` (reusable engines) and
  `agents/` (per-source configs). The first workflow is `workflows/research.py`.
- Build the research workflow as a deterministic, **acyclic** LangGraph graph:
  `initialize_state → collect_sources → route_by_status → finalize_results /
  finalize_failure`. It calls the coordinator exactly once and never re-implements
  concurrency, failure isolation, timing, ordering, aggregation, or URL dedup —
  those stay in `patterns/parallel.py`.
- The coordinator is **dependency-injected** (`Coordinator = Callable[[str],
  Awaitable[ParallelRunResult]]`), so the graph builds no real sources and the
  workflow is testable with in-process fakes and zero network.
- Contracts are three `TypedDict`s wired as the graph's separate input / state /
  output schemas: `PulseInput{query}`, `PulseState{query, parallel_result?,
  result?}`, `PulseOutput{result: ParallelRunResult}`. The output schema filters
  the public result down to `result`, so internal/routing fields never leak.
  `PulseOutput` reuses `ParallelRunResult` verbatim — no duplicate result, status,
  error, items, or timing models.
- An empty/whitespace-only query is a **validation error** (`ValueError`) raised
  in `initialize_state`, before the coordinator runs. It is deliberately **not**
  represented as `RunStatus.FAILED`, which denotes a run that actually happened
  and whose sources failed.
- The public API is a graph **factory**, `build_research_graph(coordinator)`,
  compiled once and invoked via `ainvoke`; no per-call recompilation and no
  standalone convenience runner (added only when a real caller exists).
- No `recursion_limit` is set: the graph is acyclic, so the loop guard
  AGENTS.md requires for looping graphs does not apply here.

## Consequences

- The CLI still calls `run_sources` directly; wiring `main.py` to this graph is a
  separate task. Until then the workflow is dormant core plus tests, so it appears
  as an Implemented Mermaid flow but changes no C4 container (in-process node,
  architecture update rule #3).
- Later stages (digest, drafting) attach after `finalize_results` /
  `finalize_failure` without touching the coordinator contract.
- The planned `flows/langgraph-orchestrator.mmd` (LLM planning, adaptive source
  selection, RAG routing) stays Planned and is not superseded; this core is its
  deterministic foundation.

## Alternatives Considered

- Put the graph in `patterns/`: rejected — `patterns/` holds source-neutral,
  reusable engines; a product workflow that composes them is a different layer.
- Represent the empty query as a synthetic `FAILED ParallelRunResult`: rejected —
  it would fabricate a coordinator result for a run that never happened and blur
  "invalid input" with "sources failed."
- Recompile the graph inside a per-call `run_research(query)` helper: rejected —
  needless recompilation and an API with no real caller yet; a factory returning a
  reusable compiled graph is the minimal surface.

## Related

- Architecture: [../../architecture.md](../../architecture.md)
- Flow: [../flows/research-workflow.mmd](../flows/research-workflow.mmd)
- ADR 10: source-neutral parallel fan-out contract
- ADR 14: CLI default fans out to all four sources
