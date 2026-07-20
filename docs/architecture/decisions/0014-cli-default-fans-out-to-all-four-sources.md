# 14. CLI default fans out to all four sources

Date: 2026-07-20

## Status

Accepted

## Context

ADR 10 built the source-neutral parallel coordinator and the HN adapter, but
deliberately left CLI wiring Planned; `main.py` still called `run_hn_react`
directly and printed HN/ReAct-specific output (a `-> STOP_REASON (not
looping)` line, a raw trace dump, a below-minimum warning). ADRs 11–13 added
real ArXiv, YouTube, and Newsletter adapters but likewise left the "HN-only
CLI" unchanged, since nothing consumed the adapters yet. With all four
adapters in place, the CLI needed to become the actual multi-source entry
point: run every source concurrently by default, and make partial and total
failure legible to a human running the command.

## Decision

- `main.build_runners()` returns exactly
  `[hn_runner(), arxiv_runner(), youtube_runner(), newsletter_runner()]`, in
  that fixed order. This order is not incidental: it sets both the printed
  per-source summary order and the dedup precedence that ADR 10 already
  defined as "first runner in input order wins."
- `main()` always calls
  `asyncio.run(run_sources(query, build_runners()))` and renders the full
  result via `display.print_run_summary` — one line per source (status, item
  count, elapsed time, short error code) plus one aggregate line (status,
  unique item count, total elapsed time). There is no flag to run a subset of
  sources; that is deferred (see Consequences).
- Exit code encodes aggregate status: `SUCCESS` or `PARTIAL` → exit 0 and
  print the combined deduped items — partial results (e.g. three of four
  sources succeeding) are still useful output, not a failure. `FAILED` → exit
  1 and skip the item listing and its `Total:` line entirely, so a fully
  failed run never reports a misleading item count. Argparse keeps exit 2 for
  usage errors.
- The old HN-only, ReAct-specific CLI output is removed: `print_trace`, the
  `(not looping)` line, and `warn_if_below_minimum` are deleted from
  `display.py`. HN's live step-by-step reasoning trace remains visible only
  through the existing `PULSE_VERBOSE` (stderr progress) and
  `PULSE_LOG_LEVEL` controls, since `SourceOutput` — by design in ADR 10 —
  does not carry the ReAct trace across the coordinator boundary.

## Consequences

- Supersedes the "CLI wiring... stay Planned" statement in ADR 10's
  Consequences and the "HN-only CLI is unchanged" / "HN-only CLI remain
  unchanged" statements in ADRs 11, 12, and 13. Their Decision sections (why
  each adapter is built the way it is) are unaffected and still accurate.
- A single slow or hanging source — most likely HN, being LLM-bound — sets
  the visible floor on total CLI latency. No per-source timeout is added
  here, consistent with ADR 10's position that timeouts are each source's
  responsibility.
- Adding a fifth source to the default run is a one-line change to
  `build_runners()`; no other CLI change is required.
- Detailed ReAct reasoning traces can no longer be printed after a run
  completes (only live, via `PULSE_VERBOSE`). Users who need the full
  post-hoc trace must use the library API (`run_hn_react` directly) rather
  than the CLI.
- Per-source CLI flags, adaptive source selection, and digest synthesis over
  the combined items are explicitly deferred, not designed for here.

## Alternatives Considered

- Carry the ReAct trace through `SourceOutput` so the CLI could still print
  it post-hoc: rejected — would leak a pattern-specific field into the
  source-neutral coordinator contract that ADR 10 deliberately keeps
  source-blind.
- Exit 1 whenever any single source is not `SUCCESS` (i.e. on any
  `PARTIAL`): rejected — this would make the common case (e.g. HN finishing
  below its minimum-article threshold while the other three sources fully
  succeed) look like a shell-visible failure even though useful items are
  available.
- Add a `--sources` flag to select a subset for this change: rejected as
  premature — the epic scope is "wire the existing four," not source
  selection; deferred to a future task.

## Related

- Architecture: [../../architecture.md](../../architecture.md)
- Flow: [../flows/parallel-collect.mmd](../flows/parallel-collect.mmd)
- ADR 10: source-neutral parallel fan-out contract
- Supersedes CLI-status statements in:
  [0010 source-neutral parallel fan-out contract](0010-source-neutral-parallel-fanout-contract.md),
  [0011 ArXiv API + Tavily PDF enrichment](0011-use-arxiv-api-for-metadata-and-tavily-for-bounded-pdf-enrichment.md),
  [0012 Tavily discovery + transcript API for YouTube](0012-tavily-discovery-and-transcript-api-for-youtube-source.md),
  [0013 feedparser + deterministic newsletter scoring](0013-feedparser-and-deterministic-scoring-for-newsletter-rss-collection.md)
