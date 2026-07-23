# 16. CLI invokes the research workflow graph

Date: 2026-07-23

## Status

Accepted

## Context

ADR 0015 built `workflows/research.py` — a deterministic LangGraph graph
(`build_research_graph(coordinator)`) that validates the query, calls an
injected async coordinator exactly once, and routes the aggregate status to a
typed `PulseOutput`. It was deliberately left dormant: `main.py` still called
`patterns.parallel.run_sources` directly, bypassing the graph entirely, since
no caller existed yet. That caller now needs to exist: the CLI should run
every query through the graph so it owns query validation, stage ordering,
and status routing in production, not just in tests.

## Decision

- `main.py` builds a production coordinator, `_production_coordinator`,
  binding `build_runners()` to `run_sources` — the exact
  `Callable[[str], Awaitable[ParallelRunResult]]` shape `build_research_graph`
  expects.
- `main()` compiles the graph via `build_research_graph(coordinator)` fresh on
  every CLI invocation (no caching or module-level singleton — the CLI is a
  single-shot process, so there is nothing to amortize the compilation over)
  and invokes it with `asyncio.run(graph.ainvoke({"query": args.query}))`.
- `workflows/research.py` gains a dedicated `InvalidQueryError(ValueError)`
  subclass, raised by `_initialize_state` for an empty/whitespace query
  instead of a bare `ValueError`. The CLI catches only `InvalidQueryError` —
  never bare `ValueError` — and turns it into a clean exit-2 error with no
  traceback (`raise SystemExit(2) from None`), distinct from an operational
  `RunStatus.FAILED` result (exit 1).
- The direct `asyncio.run(run_sources(args.query, build_runners()))` call in
  `main()` is removed; `run_sources` is now reached only through
  `_production_coordinator`, which the graph calls exactly once via
  `collect_sources`.

## Consequences

- Supersedes ADR 0015's Consequences statement ("The CLI still calls
  `run_sources` directly; wiring `main.py` to this graph is a separate
  task."). The workflow is no longer dormant — it is the CLI's only
  production execution path.
- No C4 container change: this is an in-process wiring change inside the
  already-`Implemented` Agent Runtime container (architecture update rule 3).
- The dedicated exception type means an unrelated operational `ValueError`
  (e.g. `run_sources`'s own `ValueError("no source runners configured")`,
  raised if `build_runners()` ever returned an empty list) is never
  misclassified as an input error — it is a plain `ValueError`, not an
  `InvalidQueryError`, so it propagates as an unhandled exception instead of
  exiting 2.
- CLI-visible behavior (per-source summary lines, aggregate line, item
  listing, exit codes for `SUCCESS`/`PARTIAL`/`FAILED`, `PULSE_VERBOSE`/
  `PULSE_LOG_LEVEL`) is unchanged; only the internal call path gained the
  graph and coordinator hop.
- Later stages (digest, drafting) still attach after `finalize_results`/
  `finalize_failure` without touching the coordinator contract, unaffected by
  this change.

## Alternatives Considered

- Compiling/caching the graph as a module-level singleton: rejected — the
  CLI is single-shot (parse, run, exit), so there is no repeated invocation to
  amortize compilation cost over; a singleton would only add global state.
- Catching bare `ValueError` around `ainvoke`: rejected — would misclassify
  any unrelated operational `ValueError` (such as `run_sources`'s own "no
  source runners configured") as a clean input error.
- Catching a broad `Exception` around `ainvoke` for a "safer" exit path:
  rejected for the same reason, one level broader, and would also swallow
  genuine programming errors.

## Related

- Architecture: [../../architecture.md](../../architecture.md)
- Flows: [../flows/research-workflow.mmd](../flows/research-workflow.mmd),
  [../flows/parallel-collect.mmd](../flows/parallel-collect.mmd)
- ADR 10: source-neutral parallel fan-out contract
- ADR 14: CLI default fans out to all four sources
- ADR 15: research workflow graph over the parallel coordinator (superseded
  Consequences statement about CLI wiring)
